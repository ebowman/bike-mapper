import pandas as pd
import pytest
from flowplan import scoring, stop_model

LAT0, LON0 = 53.35, -6.26
DLON_M = 1 / (111320 * 0.5974)  # degrees lon per metre at 53.35 N (approx)
DLAT_M = 1 / 111320


@pytest.fixture
def model():
    return stop_model.load(weights="combined")


@pytest.fixture
def index(tmp_path):
    # signal node S at +100 m east, arrival from the west (from-node at +90 m);
    # stop node T at +300 m east, arrival from the EAST (from-node at +310 m).
    def row(node, east, frm, cause, way):
        return {"node_id": node, "lat": LAT0, "lon": LON0 + east * DLON_M,
                "from_node_id": node + 1, "from_lat": LAT0,
                "from_lon": LON0 + frm * DLON_M, "way_id": way, "dir": "fwd",
                "cause": cause, "amount": 1}
    df = pd.DataFrame([row(1, 100, 90, "signal", 10), row(3, 300, 310, "stop", 11)])
    path = tmp_path / "test.index.csv"
    df.to_csv(path, index=False)
    return scoring.FlowIndex.load(path=path)


def line(a, b, n=2):
    return [(LON0 + (a + (b - a) * i / (n - 1)) * DLON_M, LAT0) for i in range(n)]


def test_signal_matching_side(model, index):
    r = scoring.score(line(0, 200), model, index)
    assert r.by_class["signal"]["events"] == 1
    assert r.by_class["stop"]["events"] == 0
    assert r.expected_stops == pytest.approx(model.p("signal"))
    assert r.expected_stop_s == pytest.approx(model.p("signal") * model.mean_stop_s("signal"))
    assert r.diagnostics["matched_nodes"] == 1
    assert r.hits[0]["cause"] == "signal"


def test_stop_wrong_direction_scores_zero(model, index):
    r = scoring.score(line(250, 400), model, index)
    assert r.expected_stops == 0
    assert r.hits == []
    # the reverse direction does match the stop node
    r2 = scoring.score(line(400, 250), model, index)
    assert r2.by_class["stop"]["events"] == 1


def test_distance_one_km(model, index):
    r = scoring.score(line(0, 1000, 11), model, index)
    assert r.distance_km == pytest.approx(1.0, rel=0.01)


def test_fewer_than_two_points(model, index):
    for pts in ([], [(LON0, LAT0)], [(LON0, LAT0), (LON0, LAT0)]):
        r = scoring.score(pts, model, index)
        assert r.distance_km == 0 and r.expected_stops == 0 and r.hits == []
        assert set(r.by_class) == set(scoring.CAUSES)


def test_outside_region(model, index):
    r = scoring.score([(13.4, 52.5), (13.41, 52.5)], model, index)
    assert r.hits == [] and r.diagnostics["matched_nodes"] == 0
    assert r.distance_km > 0


def test_duplicate_points_skipped(model, index):
    pts = line(0, 200)
    r = scoring.score([pts[0], pts[0], pts[1], pts[1]], model, index)
    assert r.by_class["signal"]["events"] == 1
