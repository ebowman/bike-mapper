import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("bco", Path(__file__).parent.parent / "scripts" / "build_cycle_overlay.py")
bco = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bco)


def test_none():
    assert bco.classify({}) == (None, None)
    assert bco.classify({"cycleway": "no"}) == (None, None)
    assert bco.classify({"cycleway": "shoulder", "cycleway:left": "crossing"}) == (None, None)


def test_lane_values():
    for v in ("lane", "shared_lane", "share_busway", "opposite_lane"):
        assert bco.classify({"cycleway": v}) == ("lane", "both")


def test_track_values():
    for v in ("track", "opposite_track", "separate"):
        assert bco.classify({"cycleway": v}) == ("track", "both")


def test_sides():
    assert bco.classify({"cycleway:left": "lane"}) == ("lane", "left")
    assert bco.classify({"cycleway:right": "track"}) == ("track", "right")
    assert bco.classify({"cycleway:both": "lane"}) == ("lane", "both")
    assert bco.classify({"cycleway:left": "lane", "cycleway:right": "lane"}) == ("lane", "both")


def test_track_beats_lane():
    assert bco.classify({"cycleway:left": "lane", "cycleway:right": "track"}) == ("track", "right")


def test_km():
    assert abs(bco.km([(0, 0), (0, 1)]) - 111.195) < 0.1
