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
