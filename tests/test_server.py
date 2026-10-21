import flow_server
import pytest
from fastapi.testclient import TestClient
from flowplan.brouter import BRouterUnavailable
from flowplan.scoring import FLOW_DIR, FlowIndex

from tests.test_candidates import FakeClient

pytestmark = pytest.mark.skipif(not (FLOW_DIR / "ireland.index.csv").exists(),
                                reason="flow index missing")
Q = "from=53.2990,-6.2825&to=53.2210,-6.2150"


@pytest.fixture(scope="module")
def index():
    return FlowIndex.load("ireland")


def app_client(index, client):
    return TestClient(flow_server.create_app("ireland", client=client, index=index))


class Down(FakeClient):
    def route(self, *a, **k):
        raise BRouterUnavailable("BRouter not reachable; start it with `scripts/run_brouter.sh serve`")


def test_health(index):
    r = app_client(index, FakeClient()).get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert j["brouter"] is True and j["region"] == "ireland" and j["index_rows"] > 0


def test_route_dublin(index):
    r = app_client(index, FakeClient()).get(f"/api/route?{Q}")
    assert r.status_code == 200
    j = r.json()
    routes = j["routes"]
    assert len(routes) >= 2
    assert [x["rank"] for x in routes] == list(range(1, len(routes) + 1))
    stops = [x["stats"]["expected_stops"] for x in routes]
    assert stops == sorted(stops)
    assert routes[0]["geometry"]["type"] == "LineString"
    assert j["timings_ms"]["total"] >= 0 and j["skipped"] == []


def test_out_of_region_400(index):
    r = app_client(index, FakeClient()).get("/api/route?from=48.1,11.5&to=53.2210,-6.2150")
    assert r.status_code == 400 and "outside" in r.json()["detail"]


def test_garbage_400(index):
    assert app_client(index, FakeClient()).get("/api/route?from=abc&to=1,2").status_code == 400


def test_n_clamped(index):
    c = app_client(index, FakeClient())
    assert c.get(f"/api/route?{Q}&n=0").json()["query"]["n"] == 1
    j = c.get(f"/api/route?{Q}&n=99").json()
    assert j["query"]["n"] == 6 and len(j["routes"]) <= 6


def test_unavailable_503(index):
    r = app_client(index, Down()).get(f"/api/route?{Q}")
    assert r.status_code == 503 and "run_brouter.sh" in r.json()["detail"]


def test_static_root(index):
    assert app_client(index, FakeClient()).get("/").status_code == 200


class OneFails(FakeClient):
    """Errors on exactly the flow_hi alt 2 request."""
    def route(self, points, profile="fastbike", alternativeidx=0, params=None):
        if (params or {}).get("flow_scale") == 2.0 and alternativeidx == 2:
            return None, "operation killed by thread-priority-watchdog after 0/1 seconds"
        return super().route(points, profile, alternativeidx, params)


def test_skipped_surfaced_and_logged(index, caplog):
    with caplog.at_level("WARNING", logger="flow_server"):
        j = app_client(index, OneFails()).get(f"/api/route?{Q}").json()
    assert j["skipped"] == [{"variant": "flow_hi", "alt": 2,
                             "error": "operation killed by thread-priority-watchdog after 0/1 seconds"}]
    msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("flow_hi" in m and "alt=2" in m and "thread-priority-watchdog" in m for m in msgs)


class Counting(FakeClient):
    calls = 0

    def route(self, *a, **k):
        self.calls += 1
        return super().route(*a, **k)


def test_model_endpoint(index):
    j = app_client(index, FakeClient()).get("/api/model").json()
    assert j["default_weight_set"] == "prior" and len(j["precedence"]) == 7
    assert sorted(j["weight_sets"]) == ["combined", "ireland", "prior"]
    for ws in j["weight_sets"].values():
        assert set(ws) == set(j["precedence"])
        assert set(ws["signal"]) == {"p", "p_lo", "p_hi", "mean_stop_s", "note"}
    assert "midway_background_p" in j


def test_weights_ireland_changes_stops(index):
    c = app_client(index, FakeClient())
    base = c.get(f"/api/route?{Q}&weights=prior").json()
    ire = c.get(f"/api/route?{Q}&weights=ireland").json()
    assert ire["weight_set"] == "ireland" and ire["settings"]["weights"] == "ireland"
    assert base["routes"][0]["stats"]["expected_stops"] != ire["routes"][0]["stats"]["expected_stops"]


def test_p_override_zero(index):
    j = app_client(index, FakeClient()).get(f"/api/route?{Q}&p_signal=0").json()
    assert j["model"]["signal"] == 0 and j["settings"]["overrides"] == {"signal": 0.0}
    for r in j["routes"]:
        assert r["stats"]["by_class"]["signal"]["expected"] == 0


def test_blend_midpoint(index):
    c = app_client(index, FakeClient())
    m = c.get("/api/model").json()["weight_sets"]
    j = c.get(f"/api/route?{Q}&weights=prior&blend_with=ireland&blend=0.5").json()
    mid = (m["prior"]["signal"]["p"] + m["ireland"]["signal"]["p"]) / 2
    assert j["model"]["signal"] == pytest.approx(mid)
    assert j["settings"]["blend"] == 0.5 and j["settings"]["blend_with"] == "ireland"


@pytest.mark.parametrize("qs,name", [
    ("p_signal=2", "p_signal"), ("p_stop=abc", "p_stop"), ("weights=nope", "weights"),
    ("blend_with=ireland", "blend"), ("blend_with=ireland&blend=1.5", "blend"),
    ("blend_with=nope&blend=0.5", "blend_with"), ("guard=9", "guard"), ("guard=-1", "guard"),
    ("guard=x", "guard"), ("scales=1,abc", "scales"), ("scales=0", "scales"),
    ("scales=1,99", "scales")])
def test_bad_settings_400(index, qs, name):
    r = app_client(index, FakeClient()).get(f"/api/route?{Q}&{qs}")
    assert r.status_code == 400 and name in r.json()["detail"]


def test_scales_custom(index):
    fc = Counting()
    c = app_client(index, fc)
    base = fc.calls
    j = c.get(f"/api/route?{Q}&scales=2,0.5").json()
    assert fc.calls == base + 12 and j["settings"]["scales"] == [2.0, 0.5]


def test_cache_and_refresh(index):
    fc = Counting()
    c = app_client(index, fc)
    base = fc.calls  # startup health check may route
    j1 = c.get(f"/api/route?{Q}").json()
    assert j1["cached"] is False and fc.calls == base + 16
    j2 = c.get(f"/api/route?{Q}&guard=2").json()  # guard does not change costs -> cache hit
    assert j2["cached"] is True and fc.calls == base + 16 and j2["timings_ms"]["brouter"] == 0
    j3 = c.get(f"/api/route?{Q}&refresh=1").json()
    assert j3["cached"] is False and fc.calls == base + 32
    c.get(f"/api/route?{Q}&scales=1")  # different scales -> different key
    assert fc.calls == base + 32 + 8


def test_cost_change_misses_cache_and_is_echoed(index):
    fc = Counting()
    c = app_client(index, fc)
    base = fc.calls
    j1 = c.get(f"/api/route?{Q}").json()
    assert fc.calls == base + 16 and j1["settings"]["brouter_costs"]["cost_signal"] == 300
    j2 = c.get(f"/api/route?{Q}&p_stop=0&router=table").json()
    assert j2["cached"] is False and fc.calls == base + 32 and j2["settings"]["router"] == "table"
    assert j2["settings"]["brouter_costs"]["cost_stop"] == 0
    j3 = c.get(f"/api/route?{Q}&p_stop=0&router=table&guard=2").json()  # same costs -> hit
    assert j3["cached"] is True and fc.calls == base + 32


def test_router_base_is_default_and_sliders_hit_cache(index):
    fc = Counting()
    c = app_client(index, fc)
    base = fc.calls
    j1 = c.get(f"/api/route?{Q}").json()
    assert j1["settings"]["router"] == "base" and fc.calls == base + 16
    costs = j1["settings"]["brouter_costs"]
    j2 = c.get(f"/api/route?{Q}&p_stop=0").json()
    assert j2["cached"] is True and fc.calls == base + 16
    assert j2["settings"]["brouter_costs"] == costs and j2["model"]["stop"] == 0
    j3 = c.get(f"/api/route?{Q}&blend_with=ireland&blend=0.5").json()
    assert j3["cached"] is True and fc.calls == base + 16
    j4 = c.get(f"/api/route?{Q}&weights=ireland").json()  # different base set -> miss once
    assert j4["cached"] is False and fc.calls == base + 32
    assert c.get(f"/api/route?{Q}&weights=ireland&p_stop=0.1").json()["cached"] is True
    assert fc.calls == base + 32
    jt = c.get(f"/api/route?{Q}&p_stop=0&router=table").json()
    assert jt["cached"] is False and fc.calls == base + 48


def test_invalid_router_400(index):
    r = app_client(index, FakeClient()).get(f"/api/route?{Q}&router=nope")
    assert r.status_code == 400 and "router" in r.json()["detail"]


def test_model_endpoint_uses_app_model_path(index, tmp_path):
    import json

    from flowplan import stop_model
    d = json.loads(stop_model.DEFAULT_PATH.read_text())
    d["midway_background_p"] = 0.123
    p = tmp_path / "m.json"
    p.write_text(json.dumps(d))
    app = flow_server.create_app(client=FakeClient(), index=index, model_path=p)
    assert TestClient(app).get("/api/model").json()["midway_background_p"] == 0.123


def test_lane_bonus_echoed_and_keyed(index):
    fc = Counting()
    c = app_client(index, fc)
    base = fc.calls
    j1 = c.get(f"/api/route?{Q}").json()
    assert j1["settings"]["lane_bonus"] == 0.7 and j1["settings"]["lanes_variant"] is False
    assert fc.calls == base + 16
    assert all("cycle_km" in r["stats"] for r in j1["routes"])
    j2 = c.get(f"/api/route?{Q}&lane_bonus=0.8").json()
    assert j2["cached"] is False and fc.calls == base + 32
    assert j2["settings"]["lane_bonus"] == 0.8
    assert c.get(f"/api/route?{Q}&lane_bonus=0.8&guard=2").json()["cached"] is True


def test_lane_bonus_applied_to_flow_variants_only(index):
    seen = []

    class Rec(FakeClient):
        def route(self, points, profile="fastbike", alternativeidx=0, params=None):
            seen.append((profile, dict(params or {})))
            return super().route(points, profile, alternativeidx, params)

    app_client(index, Rec()).get(f"/api/route?{Q}&lane_bonus=0.7")
    assert all(p.get("lane_bonus") == 0.7 for prof, p in seen if prof == "flow")
    assert all("lane_bonus" not in p for prof, p in seen if prof == "fastbike")


def test_lanes_variant_added_when_requested(index):
    seen = []

    class Rec(FakeClient):
        def route(self, points, profile="fastbike", alternativeidx=0, params=None):
            seen.append((profile, dict(params or {})))
            return super().route(points, profile, alternativeidx, params)

    c = app_client(index, Rec())
    seen.clear()  # startup health check
    j0 = c.get(f"/api/route?{Q}&refresh=1").json()
    assert j0["candidates_total"] == 16 and len(seen) == 16
    seen.clear()
    j = c.get(f"/api/route?{Q}&lanes_variant=1&refresh=1").json()
    assert j["candidates_total"] == 20 and j["settings"]["lanes_variant"] is True
    assert sorted({p["lane_bonus"] for _, p in seen if "lane_bonus" in p}) == [0.7]  # default 0.7 already below 0.8
    seen.clear()
    c.get(f"/api/route?{Q}&lanes_variant=1&lane_bonus=0.9&refresh=1")
    assert {p["lane_bonus"] for _, p in seen if "lane_bonus" in p} == {0.8, 0.9}  # 0.9 base, lanes variant 0.8
    seen.clear()
    c.get(f"/api/route?{Q}&lanes_variant=1&lane_bonus=0.6&refresh=1")
    assert {p["lane_bonus"] for _, p in seen if "lane_bonus" in p} == {0.6}


@pytest.mark.parametrize("v", ["0.4", "1.1", "abc", "nan", "inf"])
def test_bad_lane_bonus_400(index, v):
    r = app_client(index, FakeClient()).get(f"/api/route?{Q}&lane_bonus={v}")
    assert r.status_code == 400 and "lane_bonus" in r.json()["detail"]


def test_debug_adds_segments_default_does_not(index):
    c = app_client(index, FakeClient())
    plain = c.get(f"/api/route?{Q}").json()
    assert all("segments" not in r and "summary" not in r for r in plain["routes"])
    j = c.get(f"/api/route?{Q}&debug=1").json()
    assert len(j["routes"]) == len(plain["routes"])
    for r in j["routes"]:
        assert r["segments"] and all(sg["highway"] for sg in r["segments"])
        assert [sg["i"] for sg in r["segments"]] == list(range(len(r["segments"])))
        sm = r["summary"]
        assert sum(sm["km_by_highway"].values()) == pytest.approx(r["stats"]["distance_km"], rel=0.02)
        assert sm["cycle_km"]["total_km"] == pytest.approx(r["stats"]["cycle_km"]["total_km"])
        assert sm["n_node_charges"] >= 0 and sm["total_brouter_cost"] > 0
        n_hits = sum(len(sg["hits"]) for sg in r["segments"])
        assert n_hits == len(r["hits"])


def test_debug_does_not_change_ranking(index):
    c = app_client(index, FakeClient())
    a = [r["id"] for r in c.get(f"/api/route?{Q}").json()["routes"]]
    b = [r["id"] for r in c.get(f"/api/route?{Q}&debug=1").json()["routes"]]
    assert a == b


def test_assign_hits_synthetic():
    from flowplan.explain import assign_hits, cycleway_string, explain
    segs = [{"lon": -6.2800, "lat": 53.3000, "dist_m": 100, "way_tags": {"highway": "primary"}},
            {"lon": -6.2790, "lat": 53.3000, "dist_m": 66, "way_tags": {"highway": "cycleway"}},
            {"lon": -6.2780, "lat": 53.3000, "dist_m": 66,
             "way_tags": {"highway": "residential", "cycleway:left": "lane", "cycleway:right": "track"},
             "node_cost": 20.0}]
    hits = [{"lon": -6.27901, "lat": 53.30001, "cause": "signal", "p": 0.8},   # ~1 m from seg 1 end
            {"lon": -6.2780, "lat": 53.3000, "cause": "stop", "p": 0.5},
            {"lon": -6.2700, "lat": 53.3000, "cause": "give_way", "p": 0.2}]   # far: fallback nearest = last
    assert assign_hits(segs, hits) == [1, 2, 2]
    assert assign_hits([], hits) == [-1, -1, -1]
    out = explain(segs, hits, 123.0)
    assert [len(s["hits"]) for s in out["segments"]] == [0, 1, 2]
    assert out["segments"][2]["cycleway"] == "left=lane, right=track"
    assert cycleway_string({"cycleway": "lane"}) == "lane" and cycleway_string({}) is None
    assert out["summary"]["n_node_charges"] == 1 and out["summary"]["total_brouter_cost"] == 123.0
    assert out["summary"]["km_by_highway"]["primary"] == pytest.approx(0.1)
    assert out["segments"][1]["start_km"] == pytest.approx(0.1)


def test_straightness_params_flow_only_echo_and_cache(index):
    seen = []

    class Rec(FakeClient):
        def route(self, points, profile="fastbike", alternativeidx=0, params=None):
            seen.append((profile, dict(params or {})))
            return super().route(points, profile, alternativeidx, params)

    c = app_client(index, Rec())
    seen.clear()
    j = c.get(f"/api/route?{Q}&refresh=1").json()
    st = j["settings"]
    assert (st["turn_cost"], st["lane_exit_cost"], st["cycleway_base"], st["lane_bonus"]) == (400, 150, 1.0, 0.7)
    for prof, p in seen:
        if prof == "flow":
            assert (p["turn_cost"], p["lane_exit_cost"], p["cycleway_base"]) == (400, 150, 1.0)
        else:
            assert not {"turn_cost", "lane_exit_cost", "cycleway_base", "lane_bonus"} & set(p)
    seen.clear()
    j2 = c.get(f"/api/route?{Q}&turn_cost=150&lane_exit_cost=0&lane_bonus=1.0").json()
    assert j2["cached"] is False and j2["settings"]["turn_cost"] == 150
    assert {p["turn_cost"] for prof, p in seen if prof == "flow"} == {150}
    assert c.get(f"/api/route?{Q}&turn_cost=150&lane_exit_cost=0&lane_bonus=1.0").json()["cached"] is True
    assert c.get(f"/api/route?{Q}&turn_cost=151&lane_exit_cost=0&lane_bonus=1.0").json()["cached"] is False


@pytest.mark.parametrize("name,v", [("turn_cost", "-1"), ("turn_cost", "2001"), ("lane_exit_cost", "1001"),
                                    ("lane_exit_cost", "-5"), ("cycleway_base", "0.4"), ("cycleway_base", "2.1"),
                                    ("turn_cost", "abc"), ("cycleway_base", "nan")])
def test_bad_straightness_400(index, name, v):
    r = app_client(index, FakeClient()).get(f"/api/route?{Q}&{name}={v}")
    assert r.status_code == 400 and name in r.json()["detail"]
