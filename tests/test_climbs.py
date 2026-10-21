import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest
from flowplan.brouter import parse_geojson
from flowplan.climbs import (
    Climb,
    climb_score,
    detect_climbs,
    detect_on_profile,
    elevation_stats,
)

ROOT = Path(__file__).parent.parent
M_PER_DEG_LAT = 111194.9


def line(length_m, spacing=25.0):
    """Straight north-south line of points `spacing` metres apart; returns (coords, distances)."""
    n = int(length_m / spacing) + 1
    d = [i * spacing for i in range(n)]
    return [(-6.0, 53.0 + x / M_PER_DEG_LAT) for x in d], d


def profile(d, fn):
    return [fn(x) for x in d]


def test_flat_line():
    coords, d = line(5000)
    ele = profile(d, lambda x: 50.0)
    assert detect_climbs(coords, ele) == []
    st = elevation_stats(coords, ele)
    assert st == {"ascent_m": 0.0, "descent_m": 0.0, "max_ele": 50.0, "min_ele": 50.0}
    assert climb_score([]) == {"score": 0.0, "hardest": None, "n_climbs": 0}


def test_single_ramp():
    coords, d = line(5000)
    ele = profile(d, lambda x: 0.06 * x)
    climbs = detect_climbs(coords, ele)
    assert len(climbs) == 1
    c = climbs[0]
    assert isinstance(c, Climb)
    assert c.gain_m == pytest.approx(300, rel=0.05)
    assert c.avg_grade_pct == pytest.approx(6.0, rel=0.05)
    assert c.max_500m_grade_pct == pytest.approx(6.0, rel=0.05)
    assert c.points > 150 and c.category in ("3", "2")
    sc = climb_score(climbs)
    assert sc["score"] == c.points and sc["hardest"] is c and sc["n_climbs"] == 1
    st = elevation_stats(coords, ele)
    assert st["ascent_m"] == pytest.approx(300, abs=4) and st["descent_m"] == 0


def test_two_ramps_with_flat_between():
    coords, d = line(11000)

    def f(x):
        if x < 5000:
            return 0.06 * x
        if x < 6000:
            return 300.0
        return 300.0 + 0.06 * (x - 6000)

    climbs = detect_climbs(coords, profile(d, f))
    assert len(climbs) == 2
    assert climbs[0].end_km <= climbs[1].start_km
    assert climb_score(climbs)["score"] == pytest.approx(sum(c.points for c in climbs))


def test_noise_ascent_zero():
    # 3 m hysteresis: noise with peak-to-peak swing < 3 m (+-1.4 m here) never registers; a +-2 m
    # square wave (4 m swing) would, by design.
    coords, d = line(5000)
    ele = [50.0 + (1.4 if i % 2 else -1.4) for i in range(len(d))]
    assert elevation_stats(coords, ele)["ascent_m"] == 0.0
    assert detect_climbs(coords, ele) == []
    rng = np.random.default_rng(1)
    ele = [50.0 + float(v) for v in rng.uniform(-1.4, 1.4, len(d))]
    st = elevation_stats(coords, ele)
    assert st["ascent_m"] == 0.0 and st["descent_m"] == 0.0


def test_none_gaps_interpolated():
    coords, d = line(5000)
    full = profile(d, lambda x: 0.06 * x)
    gappy = list(full)
    for i in range(40, 90):
        gappy[i] = None
    gappy[0] = None  # leading None takes nearest known value
    c = detect_climbs(coords, gappy)
    assert len(c) == 1 and c[0].gain_m == pytest.approx(300, rel=0.08)
    st = elevation_stats(coords, gappy)
    assert st["max_ele"] == pytest.approx(300, abs=1) and st["ascent_m"] == pytest.approx(300, rel=0.05)
    assert detect_climbs(coords, [None] * len(coords)) == []
    assert elevation_stats(coords, [None] * len(coords))["max_ele"] is None


def test_degenerate_inputs():
    assert detect_climbs([], []) == []
    assert detect_climbs([(0, 0)], [1.0]) == []
    assert detect_climbs([(0, 0), (0, 0)], [1.0, 2.0]) == []
    assert elevation_stats([], [])["ascent_m"] == 0.0


def test_irregular_spacing_not_biased():
    """Same 6% ramp with wildly uneven node spacing gives the same answer as even spacing."""
    rng = np.random.default_rng(2)
    d = np.sort(np.concatenate([[0, 5000], rng.uniform(0, 5000, 150)]))
    coords = [(-6.0, 53.0 + x / M_PER_DEG_LAT) for x in d]
    c = detect_climbs(coords, [0.06 * x for x in d])
    assert len(c) == 1 and c[0].avg_grade_pct == pytest.approx(6.0, rel=0.05)


def test_wicklow_gap_glo30_profile():
    with open(ROOT / "data/samples/wicklow_gap_profile_glo30.csv") as f:
        rows = list(csv.DictReader(f))
    d = np.array([float(r["distance_m"]) for r in rows])
    z = np.array([float(r["elevation_m"]) for r in rows])
    climbs = detect_on_profile(d, z)
    assert len(climbs) == 1
    c = climbs[0]
    assert c.length_m == pytest.approx(6575, rel=0.10)
    assert c.gain_m == pytest.approx(332, rel=0.10)
    assert c.points == pytest.approx(204, rel=0.15)
    assert c.avg_grade_pct == pytest.approx(5.05, rel=0.10)
    assert c.category == "3"
    # same through the public API, via (lon, lat) coords built from the CSV
    coords = [(float(r["lon"]), float(r["lat"])) for r in rows]
    c2 = detect_climbs(coords, list(z))
    assert len(c2) == 1 and c2[0].gain_m == pytest.approx(332, rel=0.10)
    assert c2[0].points == pytest.approx(204, rel=0.15)


def test_brouter_fixture_runs():
    cand = parse_geojson(json.loads((ROOT / "tests/fixtures/brouter_dublin_flow_alt0.json").read_text()))
    assert any(e is not None for e in cand.elevations)
    climbs = detect_climbs(cand.geometry, cand.elevations)
    assert isinstance(climbs, list)
    st = elevation_stats(cand.geometry, cand.elevations)
    assert st["ascent_m"] >= 0 and not math.isnan(st["max_ele"])
    print("fixture climbs:", climbs, "stats:", st, "brouter ascent:", cand.ascent_m)
