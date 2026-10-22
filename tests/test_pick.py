import flow_mcp
import flow_server
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flowplan.pick import PickStore
from flowplan.pick import register as register_pick
from flowplan.scoring import FLOW_DIR

TOK = "abcDEF123_-x"
PTS = {"points": [{"lat": 53.3, "lon": -6.26, "label": "Home"}, {"lat": 53.2, "lon": -6.1}]}


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def api():
    clock = Clock()
    app = FastAPI()
    register_pick(app, PickStore(ttl_s=600, clock=clock))
    return TestClient(app), clock


def test_store_get_404_and_expiry(api):
    c, clock = api
    assert c.get(f"/api/pick/{TOK}").status_code == 404
    r = c.post(f"/api/pick/{TOK}", json=PTS)
    assert r.status_code == 200
    g = c.get(f"/api/pick/{TOK}").json()
    assert g["points"] == [{"lat": 53.3, "lon": -6.26, "label": "Home"}, {"lat": 53.2, "lon": -6.1}]
    assert g["created_at"] == 1000.0
    clock.t += 599
    assert c.get(f"/api/pick/{TOK}").status_code == 200
    clock.t += 2
    assert c.get(f"/api/pick/{TOK}").status_code == 404


@pytest.mark.parametrize("tok", ["short", "bad token!!", "x" * 65])
def test_bad_token_400(api, tok):
    c, _ = api
    assert c.post(f"/api/pick/{tok}", json=PTS).status_code == 400
    assert c.get(f"/api/pick/{tok}").status_code == 400


@pytest.mark.parametrize("body", [
    {}, {"points": []}, {"points": "x"}, {"points": [{"lat": 1, "lon": 1}] * 3},
    {"points": [{"lat": 91, "lon": 0}]}, {"points": [{"lat": 0, "lon": 181}]},
    {"points": [{"lat": "a", "lon": 0}]}, {"points": [{"lon": 0}]}, {"points": [5]},
])
def test_bad_points_400(api, body):
    c, _ = api
    assert c.post(f"/api/pick/{TOK}", json=body).status_code == 400


@pytest.mark.skipif(not (FLOW_DIR / "ireland.index.csv").exists(), reason="flow index missing")
def test_wired_into_create_app():
    from tests.test_candidates import FakeClient
    c = TestClient(flow_server.create_app("ireland", client=FakeClient()))
    assert c.post(f"/api/pick/{TOK}", json=PTS).status_code == 200
    assert len(c.get(f"/api/pick/{TOK}").json()["points"]) == 2


# ---- MCP pick_points ----
@pytest.fixture
def mcp_stubs(monkeypatch):
    opened = []
    monkeypatch.setattr(flow_mcp.webbrowser, "open", lambda u: opened.append(u) or True)
    monkeypatch.setattr(flow_mcp.time, "sleep", lambda s: None)
    return opened


def test_pick_points_returns_points_on_second_poll(monkeypatch, mcp_stubs):
    calls = []

    def fetch(token):
        calls.append(token)
        return None if len(calls) <= 2 else {"points": [{"lat": 53.3, "lon": -6.26, "label": "Home"},
                                                         {"lat": 53.2, "lon": -6.1}], "created_at": 1}
    monkeypatch.setenv("FLOW_PLANNER_URL", "http://example.test:9/")
    monkeypatch.setattr(flow_mcp, "_fetch_pick", fetch)
    out = flow_mcp.pick_points(n=2, timeout_s=60)
    assert "53.300000,-6.260000 (Home)" in out and "53.200000,-6.100000" in out and "plan_route" in out
    assert len(calls) == 3 and len(set(calls)) == 1
    assert mcp_stubs == [f"http://example.test:9/#pick={calls[0]}&n=2"]
    assert len(calls[0]) >= 8


def test_pick_points_timeout(monkeypatch, mcp_stubs):
    monkeypatch.setattr(flow_mcp, "_fetch_pick", lambda t: None)
    out = flow_mcp.pick_points(n=1, timeout_s=0)
    assert out.startswith("Error: timed out") and len(mcp_stubs) == 1


def test_pick_points_server_down(monkeypatch, mcp_stubs):
    def boom(t):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(flow_mcp, "_fetch_pick", boom)
    assert flow_mcp.pick_points() == "Error: planner web server not running (make planner)"
    assert mcp_stubs == []
    assert flow_mcp.pick_points(n=3).startswith("Error: n must be")
