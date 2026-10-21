import itertools
import json
from pathlib import Path

import gpxpy
import pytest
from flowplan.brouter import parse_geojson
from flowplan.gpx import gpx_string, write_gpx
from gpxpy.geo import haversine_distance

FIX = Path(__file__).parent / "fixtures"
COORDS = [(-6.2825 + i * 0.001, 53.2990 - i * 0.0007) for i in range(20)]
ELEV = [10.0 + i * 0.5 for i in range(20)]


def test_round_trip(tmp_path):
    p = write_gpx(tmp_path / "r.gpx", "Test", COORDS, ELEV, desc="d")
    text = p.read_text(encoding="utf-8")
    assert text.startswith('<?xml version="1.0"')
    g = gpxpy.parse(text)
    assert g.version == "1.1"
    assert 'version="1.1"' in text.split("\n")[1]
    pts = g.tracks[0].segments[0].points
    assert len(pts) == 20
    assert (pts[0].longitude, pts[0].latitude) == pytest.approx(COORDS[0], abs=1e-6)
    assert (pts[-1].longitude, pts[-1].latitude) == pytest.approx(COORDS[-1], abs=1e-6)
    hav = sum(haversine_distance(a[1], a[0], b[1], b[0]) for a, b in itertools.pairwise(COORDS))
    assert g.tracks[0].length_2d() == pytest.approx(hav, rel=0.001)
    assert [pt.elevation for pt in pts] == pytest.approx(ELEV, abs=0.05)
    assert g.description == "d" and g.time is not None


def test_escaping():
    g = gpxpy.parse(gpx_string("A & B <x>", COORDS, desc="1 < 2 & 3"))
    assert g.tracks[0].name == "A & B <x>"
    assert g.description == "1 < 2 & 3"


def test_no_elevations_omits_ele():
    g = gpxpy.parse(gpx_string("n", COORDS, [None] + ELEV[1:]))
    pts = g.tracks[0].segments[0].points
    assert pts[0].elevation is None and pts[1].elevation is not None
    assert "<ele>" not in gpx_string("n", COORDS)


def test_errors():
    with pytest.raises(ValueError):
        gpx_string("n", COORDS[:1])
    with pytest.raises(ValueError):
        gpx_string("n", [(0.0, 0.0)] * 100_001)
    with pytest.raises(ValueError):
        gpx_string("n", COORDS, ELEV[:3])


def test_course_points_only_when_given():
    assert "<rte>" not in gpx_string("n", COORDS)
    g = gpxpy.parse(gpx_string("n", COORDS, course_points=[(COORDS[3][0], COORDS[3][1], "Turn <left>")]))
    assert len(g.routes) == 1 and g.routes[0].points[0].name == "Turn <left>"


def test_fixture_elevations(tmp_path):
    data = json.loads((FIX / "brouter_dublin_flow_alt0.json").read_text())
    c = parse_geojson(data, profile="flow")
    assert len(c.elevations) == len(c.geometry)
    p = write_gpx(tmp_path / "f.gpx", "Dublin", c.geometry, c.elevations)
    g = gpxpy.parse(p.read_text(encoding="utf-8"))
    pts = g.tracks[0].segments[0].points
    assert len(pts) == len(c.geometry)
    assert all(pt.elevation is not None for pt in pts)
