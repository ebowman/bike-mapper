import flow_server
import pytest
from fastapi.testclient import TestClient
from flowplan.brouter import BRouterUnavailable
from flowplan.ranking import ScoredCandidate, rank
from flowplan.scoring import FLOW_DIR, FlowIndex
from flowplan.terrain import Dem

from tests.test_plan import FakeClient as PlanFake

pytestmark = pytest.mark.skipif(not (FLOW_DIR / "ireland.index.csv").exists(), reason="flow index missing")
FROM = "from=53.2990,-6.2825"
LOOP = f"/api/plan?mode=loop&{FROM}&length_km=45&bearings=4"


class Hilly(PlanFake):
    """Elevation ramp whose steepness depends on the route's first via-point, so candidates differ."""
    def route(self, points, profile="fastbike", alternativeidx=0, params=None):
        c, err = super().route(points, profile, alternativeidx, params)
        if c is not None:
            k = 1 + int(abs(points[1][0] * 1000)) % 5
            n = len(c.geometry)
            c.elevations = [10.0 + 60 * k * min(i, n - 1 - i) for i in range(n)]
        return c, err


class Counting(Hilly):
    def route(self, *a, **k):
        self.n = getattr(self, "n", 0) + 1
        return super().route(*a, **k)


@pytest.fixture(scope="module")
def index():
    return FlowIndex.load("ireland")


def app(index, client=None):
    return TestClient(flow_server.create_app("ireland", client=client or Hilly(), index=index,
                                             dem=Dem(paths=[])))


def test_loop_in_range_with_climb_fields(index):
    r = app(index).get(LOOP)
    assert r.status_code == 200
    j = r.json()
    assert j["routes"] and j["plan"]["mode"] == "loop" and j["plan"]["length_range"] == [40.5, 49.5]
    assert j["plan"]["calls"] > 0 and j["plan"]["objective"] == "flow"
    for x in j["routes"]:
        st = x["stats"]
        assert 40.5 <= st["distance_km"] <= 49.5
        assert st["ascent_m"] > 0 and st["descent_m"] is not None
        assert isinstance(st["climbs"], list) and "climb_score" in st and "hardest_climb" in st
        assert x["plan"]["mode"] == "loop" and "expected_stops" in st and "turns" in st


@pytest.mark.parametrize("q", [LOOP, LOOP + "&objective=climb&n=6", LOOP + "&n=6",
                               f"/api/plan?mode=out_and_back&{FROM}&min_km=50&max_km=60&bearings=4&n=6",
                               f"/api/plan?mode=one_way&{FROM}&to=53.2210,-6.2150&n=6"])
def test_route_ids_unique_in_plan(index, q):
    ids = [x["id"] for x in app(index).get(q).json()["routes"]]
    assert ids and len(ids) == len(set(ids))
    if "one_way" not in q:
        assert all("@" in i for i in ids)


def test_objective_climb_orders_by_score(index):
    j = app(index).get(LOOP + "&objective=climb&n=6").json()
    cs = [x["stats"]["climb_score"] for x in j["routes"]]
    assert len(set(cs)) > 1 and cs == sorted(cs, reverse=True) and cs[0] > 0


def test_objective_flat_orders_by_ascent(index):
    j = app(index).get(LOOP + "&objective=flat&n=6").json()
    asc = [x["stats"]["ascent_m"] for x in j["routes"]]
    assert len(set(asc)) > 1 and asc == sorted(asc)


def test_one_way_requires_to(index):
    r = app(index).get(f"/api/plan?mode=one_way&{FROM}")
    assert r.status_code == 400 and "'to'" in r.json()["detail"]
    j = app(index).get(f"/api/plan?mode=one-way&{FROM}&to=53.2210,-6.2150").json()
    assert j["plan"]["mode"] == "one_way" and j["routes"] and j["plan"]["length_range"] is None


@pytest.mark.parametrize("mode", ["out_and_back", "out-and-back"])
def test_out_and_back_modes(index, mode):
    j = app(index).get(f"/api/plan?mode={mode}&{FROM}&min_km=50&max_km=60&bearings=4").json()
    assert j["plan"]["mode"] == "out_and_back" and j["plan"]["length_range"] == [50, 60]
    assert j["routes"] and all(50 <= x["stats"]["distance_km"] <= 60 for x in j["routes"])


def test_out_and_back_explicit_end_notes_objective(index):
    j = app(index).get(f"/api/plan?mode=out_and_back&{FROM}&to=53.2210,-6.2150&objective=climb").json()
    assert j["routes"] and any("explicit end" in n for n in j["plan"]["notes"])


def test_cache_hit_and_turn_weight_rerank(index):
    cl = Counting()
    c = app(index, cl)
    a = c.get(LOOP).json()
    n = cl.n
    assert a["cached"] is False and n > 0
    b = c.get(LOOP).json()
    assert b["cached"] is True and cl.n == n and b["timings_ms"]["brouter"] == 0
    d = c.get(LOOP + "&turn_weight=1.5").json()
    assert d["cached"] is True and cl.n == n and d["settings"]["turn_weight"] == 1.5
    e = c.get(LOOP + "&objective=climb").json()     # different via-point strategy: re-plans
    assert e["cached"] is False
    m = cl.n
    f = c.get(LOOP + "&objective=climb&diversity=0.2").json()       # ranking-only: cache hit
    assert f["cached"] is True and cl.n == m and f["settings"]["diversity"] == 0.2
    assert c.get(LOOP).json()["settings"]["diversity"] == 0.7
    assert c.get(LOOP + "&refresh=1").json()["cached"] is False


@pytest.mark.parametrize("q,name", [
    ("mode=bogus&length_km=45", "mode"), ("length_km=45&objective=hilly", "objective"),
    ("length_km=-5", "length_km"), ("length_km=abc", "length_km"), ("", "length_km"),
    ("min_km=50", "min_km"), ("min_km=60&max_km=50", "min_km"), ("length_km=45&min_km=40&max_km=50", "length_km"),
    ("length_km=45&n=9", "n"), ("length_km=45&bearings=2", "bearings"), ("length_km=45&bearings=13", "bearings"),
    ("length_km=45&max_calls=97", "max_calls"), ("length_km=45&return=maybe", "return"),
    ("length_km=45&turn_weight=9", "turn_weight"),
    ("length_km=45&diversity=1.5", "diversity"), ("length_km=45&diversity=-0.1", "diversity"),
    ("length_km=45&diversity=abc", "diversity"), ("length_km=45&p_signal=2", "p_signal"),
])
def test_plan_400s_name_parameter(index, q, name):
    r = app(index).get(f"/api/plan?{FROM}&{q}")
    assert r.status_code == 400 and f"'{name}'" in r.json()["detail"]


def test_missing_from_and_out_of_region(index):
    assert app(index).get("/api/plan?length_km=45").status_code == 400
    assert app(index).get("/api/plan?from=48.1,11.5&length_km=45").status_code == 400


def test_brouter_down_503(index):
    class Down(PlanFake):
        def route(self, *a, **k):
            raise BRouterUnavailable("BRouter not reachable")
    assert app(index, Down()).get(LOOP).status_code == 503


def test_max_calls_limits(index):
    cl = Counting()
    c = app(index, cl)
    base = cl.n        # the startup health check goes through route()
    r = c.get(LOOP + "&max_calls=4")
    assert cl.n - base <= 4 and r.status_code == 404 and "max_calls=4" in r.json()["detail"]


def test_route_endpoint_has_climb_stats(index):
    from tests.test_candidates import FakeClient
    j = TestClient(flow_server.create_app("ireland", client=FakeClient(), index=index)).get(
        "/api/route?from=53.2990,-6.2825&to=53.2210,-6.2150").json()
    assert all("climb_score" in x["stats"] and "ascent_m" in x["stats"] for x in j["routes"])


def test_rank_objectives_and_range_unit():
    from flowplan.brouter import Candidate
    from flowplan.scoring import RouteScore

    def sc(name, km, asc, climb, stops):
        c = Candidate(name, "flow", 0, [], km * 1000, asc, 0, 0)
        rs = RouteScore.__new__(RouteScore)
        rs.expected_stops, rs.turns, rs.longest_straight_km = stops, 0, 1.0
        return ScoredCandidate(c, rs, extra={"ascent_m": asc, "climb_score": climb})
    s = [sc("a", 45, 300, 10, 1.0), sc("b", 45, 100, 50, 2.0), sc("c", 70, 10, 99, 0.1)]
    assert [x.cand.variant for x in rank(s, objective="climb", length_range=(40, 50))] == ["b", "a"]
    assert [x.cand.variant for x in rank(s, objective="flat", length_range=(40, 50))] == ["b", "a"]
    assert [x.cand.variant for x in rank(s, objective="flow", length_range=(40, 50))] == ["a", "b"]
    assert rank(s, objective="flow", length_range=(1, 2)) == []
    with pytest.raises(ValueError):
        rank(s, objective="x")


def test_duplicate_of_matches_kept_key():
    from flowplan.candidates import DEFAULT_VARIANTS
    from flowplan.plan import plan_candidates

    from tests.test_plan import START
    res = plan_candidates(PlanFake(), "loop", START, length_km=(40, 50), bearings=2,
                          variants=tuple(v for v in DEFAULT_VARIANTS if v.name in ("fastbike", "flow")))
    kept = {c.route_id for c in res.kept}
    assert len(kept) == len(res.kept)
    dup = [c for c in res.dropped if c.duplicate_of and "overlap" not in c.duplicate_of]
    assert dup
    for c in dup:
        assert "@" in c.duplicate_of and c.duplicate_of in kept


def _two_same_heading(monkeypatch):
    """Climb objective whose DEM selection yields two via-point sets at the same heading, different radii."""
    from flowplan import plan as plan_mod

    def fake(objective, mode, dem, start, d0, bearings, region, res, target_m):
        return [plan_mod._State(90.0, d0 * 0.88, polar=[(90.0, d0), (210.0, d0), (330.0, d0)], param0=d0,
                                scores=[1.0, 1.0, 1.0]),
                plan_mod._State(90.0, d0 * 0.94, polar=[(90.0, d0), (210.0, d0), (330.0, d0)], param0=d0,
                                scores=[1.0, 1.0, 1.0])]
    monkeypatch.setattr(plan_mod, "_objective_states", fake)


def test_same_heading_sets_get_unique_ids(index, monkeypatch):
    _two_same_heading(monkeypatch)
    j = app(index).get(LOOP + "&objective=climb&n=6").json()
    ids = [x["id"] for x in j["routes"]]
    assert len(ids) == len(set(ids))
    assert {x["plan"]["set"] for x in j["routes"]} == {0, 1}
    assert all("@90." in i for i in ids)
    assert len({round(x["stats"]["distance_km"], 3) for x in j["routes"]}) > 1


def test_dedupe_does_not_confuse_same_heading_sets(index, monkeypatch):
    _two_same_heading(monkeypatch)
    from flowplan.plan import plan_candidates
    res = plan_candidates(Hilly(), "loop", (-6.2825, 53.2990), length_km=(40.5, 49.5), bearings=4,
                          objective="climb")
    kept = {c.route_id for c in res.kept}
    assert len(kept) == len(res.kept)
    assert all(c.duplicate_of in kept for c in res.dropped if "@" in (c.duplicate_of or ""))


def test_ride_warnings_flags_unrideable_ways():
    from flowplan.explain import ride_warnings
    seg = lambda d, **t: {"dist_m": d, "way_tags": t}
    assert ride_warnings([seg(1000, highway="primary"), seg(500, highway="path", bicycle="yes")]) == []
    w = ride_warnings([seg(1000, highway="primary"), seg(2600, highway="path", surface="ground", bicycle="no",
                                                       smoothness="impassable"),
                       seg(400, highway="footway"), seg(300, highway="footway", bicycle="designated")])
    assert len(w) == 3 and all(x.startswith("routes over unrideable ways") for x in w)
    assert "2.6 km on ways tagged bicycle=no" in w[0]
    assert "2.6 km on ways with smoothness" in w[1]
    assert "3.0 km on highway=path/footway" in w[2]
    assert ride_warnings([seg(100, highway="track", smoothness="horrible")]) == [
        "routes over unrideable ways: 0.1 km on ways with smoothness impassable/very_horrible/horrible"]
    assert ride_warnings([]) == [] and ride_warnings([{"dist_m": 5}]) == []


class Segmented(Hilly):
    """Baseline (flow_scale 0) candidates on 'dirty' headings (first via-point lon bucket even) carry a ride
    warning (path without bicycle=yes); every other candidate is clean."""
    @staticmethod
    def dirty(points):
        return int(abs(points[1][0] * 1000)) % 2 == 0

    def route(self, points, profile="fastbike", alternativeidx=0, params=None):
        c, err = super().route(points, profile, alternativeidx, params)
        if c is not None:
            base = (params or {}).get("flow_scale") == 0
            if base:  # distinct geometry so dedupe does not merge it into the flow candidate
                g = c.geometry
                c.geometry = [g[0]] + [(x + 0.03, y + 0.03) for x, y in g[1:-1]] + [g[-1]]
            tags = {"highway": "path"} if base and self.dirty(points) else {"highway": "tertiary"}
            c.segments = [{"lon": c.geometry[-1][0], "lat": c.geometry[-1][1], "dist_m": c.length_m,
                           "way_tags": tags, "node_cost": 0, "initial_cost": 0, "turn_cost": 0,
                           "cost_per_km": 1000.0, "time_s": c.time_s}]
        return c, err


def _plan_capture(index, client):
    """Run svc.plan_scored for the loop query and return (response, candidates handed to finish(),
    candidates in the cached plan result)."""
    from flowplan.service import PlannerService
    svc = PlannerService.create("ireland", client=client, index=index, dem=Dem(paths=[]))
    seen = {}
    orig = svc.finish

    def spy(st, kept, *a, **k):
        seen["kept"] = list(kept)
        return orig(st, kept, *a, **k)

    svc.finish = spy
    resp, _ = svc.plan_scored({"mode": "loop", "from": "53.2990,-6.2825", "length_km": "45", "bearings": "4",
                               "n": "6"})
    before = next(iter(svc.cache._d.values()))[0]
    return resp, seen["kept"], before


def _dirty(c):
    return c.segments[0]["way_tags"]["highway"] == "path"


def test_plan_keeps_warned_baseline_candidates_flagged(index):
    resp, kept, before = _plan_capture(index, Segmented())
    assert before is not None
    base = [c for c in before if c.variant == "fastbike"]
    bad = [c for c in base if _dirty(c)]
    assert bad and any(not _dirty(c) for c in base)  # setup: both kinds exist among the baseline candidates
    assert {id(c) for c in before} == {id(c) for c in kept}  # nothing is dropped any more
    assert not any("dropped" in n for n in resp["plan"]["notes"])
    # delta_vs_fastest is filled for every route, including headings whose baseline carries a warning
    assert resp["routes"] and all(r["delta_vs_fastest"] is not None for r in resp["routes"])
    flagged = [r for r in resp["routes"] if r["variant"] == "fastbike" and r["warnings"]]
    assert flagged and all(any("path" in w or "footway" in w for w in r["warnings"]) for r in flagged)
    assert all(not r["warnings"] for r in resp["routes"] if r["variant"] != "fastbike")


def test_plan_baseline_delta_never_null(index):
    class AllClean(Segmented):
        @staticmethod
        def dirty(points):
            return False

    resp, kept, before = _plan_capture(index, AllClean())
    assert len(kept) == len(before) and any(c.variant == "fastbike" for c in kept)
    assert resp["routes"] and all(r["delta_vs_fastest"] is not None for r in resp["routes"])
    assert not any(r["warnings"] for r in resp["routes"] if r["variant"] == "fastbike")
