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
