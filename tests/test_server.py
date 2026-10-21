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
