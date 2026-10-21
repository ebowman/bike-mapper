import itertools
import json
import math
from pathlib import Path

import pytest
from flowplan import brouter, candidates
from flowplan.brouter import BRouterClient, BRouterUnavailable, parse_geojson
from flowplan.candidates import DEFAULT_VARIANTS, Variant, dedupe, generate
from flowplan.scoring import haversine_m

FIX = Path(__file__).parent / "fixtures"
A, B = (-6.2825, 53.2990), (-6.2150, 53.2210)


class FakeClient(BRouterClient):
    """Replays fixtures; `missing` profiles return a text error like BRouter does."""
    def __init__(self, missing=()):
        super().__init__()
        self.missing = set(missing)

    def route(self, points, profile="fastbike", alternativeidx=0, params=None):
        scale = (params or {}).get("flow_scale")
        name = {None: profile, 0.5: "flow_lo", 1.0: "flow", 2.0: "flow_hi"}[scale]
        if profile in self.missing:
            return None, "operation failed: profile not found"
        data = json.loads((FIX / f"brouter_dublin_{name}_alt{alternativeidx}.json").read_text())
        return parse_geojson(data, profile=profile, alt=alternativeidx, params=params), None


def test_fixture_count():
    assert len(list(FIX.glob("brouter_dublin_*_alt*.json"))) == 16


def test_parse_length_matches_track_length():
    data = json.loads((FIX / "brouter_dublin_fastbike_alt0.json").read_text())
    c = parse_geojson(data, profile="fastbike")
    g = c.geometry
    assert all(len(p) == 2 for p in g)  # elevation dropped
    length = sum(haversine_m(*a, *b) for a, b in itertools.pairwise(g))
    assert length == pytest.approx(c.length_m, rel=0.01)
    assert c.ascent_m > 0 and c.time_s > 0 and c.cost > 0


def test_generate_dedupe_bounds():
    kept, dropped, _ = generate(FakeClient(), A, B)
    assert 3 <= len(kept) <= 16
    assert len(kept) + len(dropped) == 16
    assert kept[0].key == "fastbike/alt0"
    assert all(d.duplicate_of for d in dropped)
    keys = {k.key for k in kept}
    assert all(d.duplicate_of in keys for d in dropped)


def test_dedupe_identical_dropped():
    data = json.loads((FIX / "brouter_dublin_fastbike_alt0.json").read_text())
    c1 = parse_geojson(data, "fastbike", "fastbike", 0)
    c2 = parse_geojson(data, "x", "fastbike", 1)
    kept, dropped = dedupe([c1, c2])
    assert kept == [c1] and dropped[0].duplicate_of == "fastbike/alt0"


def test_missing_profile_skipped():
    kept, dropped, skipped = generate(FakeClient(missing={"fastbike"}), A, B)
    assert kept and all(c.profile != "fastbike" for c in kept + dropped)
    assert len(skipped) == 4 and skipped[0]["variant"] == "fastbike"
    assert "profile not found" in skipped[0]["error"]


def test_start_equals_end():
    assert generate(FakeClient(), A, A) == ([], [], [])


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text

    def json(self):
        return json.loads(self.text)


def test_text_error_body_returns_none(monkeypatch):
    monkeypatch.setattr(brouter.requests, "get",
                        lambda *a, **k: _Resp(200, "no track found"))
    cl = BRouterClient()
    c, err = cl.route([A, B], "fastbike")
    assert c is None and "no track found" in err


def test_non_200_returns_none(monkeypatch):
    monkeypatch.setattr(brouter.requests, "get", lambda *a, **k: _Resp(500, "boom"))
    cl = BRouterClient()
    c, err = cl.route([A, B], "fastbike")
    assert c is None and "500" in err


def test_connection_refused_raises():
    cl = BRouterClient("http://127.0.0.1:1")
    with pytest.raises(BRouterUnavailable, match="run_brouter.sh serve"):
        cl.route([A, B], "fastbike")
    assert cl.health() is False


def test_request_params(monkeypatch):
    seen = {}

    def get(url, params, timeout):
        seen.update(params)
        return _Resp(200, "x")
    monkeypatch.setattr(brouter.requests, "get", get)
    BRouterClient().route([A, B], "flow", 2, {"flow_scale": 0.5})
    assert seen["profile"] == "flow" and seen["profile:flow_scale"] == 0.5
    assert seen["alternativeidx"] == 2 and seen["format"] == "geojson"


@pytest.mark.parametrize("bad", [0, -1, math.nan, math.inf, 10.5, "abc", "", None])
def test_flow_scale_validation(bad):
    with pytest.raises(ValueError):
        BRouterClient().route([A, B], "flow", 0, {"flow_scale": bad})
    with pytest.raises(ValueError):
        generate(FakeClient(), A, B, variants=(Variant("v", "flow", {"flow_scale": bad}),))


def test_default_variants():
    assert [v.name for v in DEFAULT_VARIANTS] == ["fastbike", "flow_lo", "flow", "flow_hi"]
    assert candidates.DEFAULT_VARIANTS[1].params == {"flow_scale": 0.5}


def test_generate_profile_params_passthrough():
    seen = []

    class Rec(FakeClient):
        def route(self, points, profile="fastbike", alternativeidx=0, params=None):
            seen.append((profile, dict(params or {})))
            return super().route(points, profile, alternativeidx, params)

    generate(Rec(), A, B, profile_params={"cost_stop": 0})
    flow = [p for pr, p in seen if pr == "flow"]
    assert len(flow) == 12 and all(p["cost_stop"] == 0 and "flow_scale" in p for p in flow)
    assert [p for pr, p in seen if pr == "fastbike"] == [{}] * 4
    with pytest.raises(ValueError):
        generate(Rec(), A, B, profile_params={"cost_stop": 5000})


@pytest.mark.parametrize("v", [0.5, 0.7, 1.0, "0.8"])
def test_lane_bonus_valid(v):
    assert brouter.validate_params({"lane_bonus": v})["lane_bonus"] == v


@pytest.mark.parametrize("v", [0.49, 1.01, 0, -1, float("nan"), float("inf"), "x", None])
def test_lane_bonus_invalid(v):
    with pytest.raises(ValueError):
        brouter.validate_params({"lane_bonus": v})


def test_parse_geojson_messages_segments():
    data = json.loads((FIX / "brouter_dublin_flow_alt0.json").read_text())
    c = parse_geojson(data, profile="flow")
    assert len(c.segments) == len(data["features"][0]["properties"]["messages"]) - 1 > 10
    s = c.segments[2]
    assert set(s) == {"lon", "lat", "dist_m", "way_tags", "node_cost", "initial_cost",
                      "turn_cost", "cost_per_km", "time_s"}
    assert -7 < s["lon"] < -6 and 53 < s["lat"] < 54
    assert "highway" in s["way_tags"] or s["way_tags"] == {} or s["way_tags"]
    assert sum(x["dist_m"] for x in c.segments) == pytest.approx(c.length_m, rel=0.02)
    assert sum(x["time_s"] for x in c.segments) == pytest.approx(c.time_s, rel=0.05)


def test_parse_messages_tolerates_missing_columns():
    msgs = [["Longitude", "Latitude", "Distance", "WayTags"],
            ["-6283760", "53298290", "10", "highway=cycleway surface=asphalt"],
            ["-6283000", "53298000", "x"]]
    segs = brouter.parse_messages(msgs)
    assert segs[0]["way_tags"] == {"highway": "cycleway", "surface": "asphalt"}
    assert segs[0]["dist_m"] == 10 and segs[0]["node_cost"] == 0 and segs[0]["lon"] == -6.28376
    assert segs[1]["dist_m"] == 0 and segs[1]["way_tags"] == {}
    assert brouter.parse_messages(None) == [] and brouter.parse_messages([["Longitude"]]) == []


def test_cycle_km_synthetic():
    def seg(d, **t):
        return {"dist_m": d, "way_tags": t}
    segs = [seg(1000, highway="cycleway"), seg(500, highway="residential", cycleway="lane"),
            seg(250, highway="primary", **{"cycleway:left": "track", "cycleway:right": "lane"}),
            seg(2000, highway="residential"), seg(100, highway="tertiary", cycleway="no"),
            seg(150, highway="residential", **{"cycleway:both": "shared_lane"})]
    k = brouter.cycle_km(segs)
    assert k == pytest.approx({"path": 1.0, "lane": 0.65, "track": 0.25, "total_km": 4.0})
    assert brouter.cycle_km([]) == {"path": 0.0, "lane": 0.0, "track": 0.0, "total_km": 0.0}


def test_lanes_variant_helper():
    assert candidates.lanes_variant(1.0).params == {"flow_scale": 1.0, "lane_bonus": 0.8}
    assert candidates.lanes_variant(0.7).params["lane_bonus"] == 0.7
    assert candidates.lanes_variant(0.9).name == "flow_lanes"


@pytest.mark.parametrize("k,v", [("turn_cost", 0), ("turn_cost", 2000), ("turn_cost", "400"), ("lane_exit_cost", 0),
                                 ("lane_exit_cost", 1000), ("cycleway_base", 0.5), ("cycleway_base", 2.0)])
def test_straightness_valid(k, v):
    assert brouter.validate_params({k: v})[k] == v


@pytest.mark.parametrize("k,v", [("turn_cost", -1), ("turn_cost", 2000.1), ("lane_exit_cost", 1001),
                                 ("lane_exit_cost", -0.1), ("cycleway_base", 0.49), ("cycleway_base", 2.01),
                                 ("turn_cost", float("nan")), ("cycleway_base", "x"), ("lane_exit_cost", None)])
def test_straightness_invalid(k, v):
    with pytest.raises(ValueError):
        brouter.validate_params({k: v})
