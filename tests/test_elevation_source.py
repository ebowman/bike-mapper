"""41w.14: elevation_source auto|brouter|dem for climb stats and the GPX export."""
import flow_mcp
import gpxpy
import pytest
from flowplan.brouter import Candidate
from flowplan.climbs import elevation_stats
from flowplan.ranking import choose_elevations
from flowplan.scoring import FLOW_DIR
from flowplan.service import PlannerService, ServiceError
from flowplan.terrain import Dem, dem_route_elevations

from tests.test_plan_api import LOOP, Hilly
from tests.test_terrain import make_dem

needs_index = pytest.mark.skipif(not (FLOW_DIR / "ireland.index.csv").exists(), reason="flow index missing")
# straight line inside the synthetic tile (lon -7..-6, lat 53..54); the hill is far away so the DEM is flat 50 m
GEOM = [(-6.9, 53.1 + i * 0.001) for i in range(60)]
RAMP = [10.0 + i * 5.0 for i in range(60)]      # BRouter-style profile: +295 m


def cand():
    return Candidate("flow", "flow", 0, list(GEOM), 6000.0, 295.0, 0.0, 0.0, elevations=list(RAMP))


def test_auto_uses_dem_when_covered(tmp_path):
    dem = make_dem(tmp_path, hill=False)
    c = cand()
    out, used = choose_elevations(c, "auto", dem)
    assert used == "dem" and out is not c and c.elevations == RAMP     # a copy, the cached candidate is untouched
    assert all(abs(v - 50.0) < 1e-6 for v in out.elevations) and len(out.elevations) == len(GEOM)


def test_auto_falls_back_without_dem_or_coverage(tmp_path):
    c = cand()
    assert choose_elevations(c, "auto", Dem(paths=[])) == (c, "brouter")
    assert choose_elevations(c, "auto", None) == (c, "brouter")
    part = make_dem(tmp_path, hill=False, void_north=True)           # DEM void above lat 53.6
    far = Candidate("flow", "flow", 0, [(-6.9, 53.2 + i * 0.0075) for i in range(60)], 1.0, 0, 0, 0,
                    elevations=list(RAMP))                            # ~6 of 60 points in the void
    ele, cov = dem_route_elevations(part, far.geometry)
    assert ele is not None and 0.5 < cov < 0.95
    assert choose_elevations(far, "auto", part)[1] == "brouter"
    out, used = choose_elevations(far, "dem", part)                   # explicit dem fills the gaps
    assert used == "dem" and len(out.elevations) == 60 and all(v is not None for v in out.elevations)
    assert choose_elevations(far, "dem", Dem(paths=[]))[1] == "brouter"   # no DEM value at all
    assert choose_elevations(far, "brouter", part) == (far, "brouter")


def test_invalid_source_raises():
    with pytest.raises(ValueError):
        choose_elevations(cand(), "lidar", None)


def test_stats_differ_between_sources(tmp_path):
    dem = make_dem(tmp_path, hill=False)
    c = cand()
    b = elevation_stats(c.geometry, c.elevations)["ascent_m"]
    d = elevation_stats(c.geometry, choose_elevations(c, "dem", dem)[0].elevations)["ascent_m"]
    assert b > 250 and d == 0.0


@needs_index
def test_api_validation_echo_and_choice(tmp_path):
    import flow_server
    from fastapi.testclient import TestClient
    from flowplan.scoring import FlowIndex
    idx = FlowIndex.load("ireland")
    flat = TestClient(flow_server.create_app("ireland", client=Hilly(), index=idx, dem=make_dem(tmp_path, hill=False)))
    none = TestClient(flow_server.create_app("ireland", client=Hilly(), index=idx, dem=Dem(paths=[])))
    j = flat.get(LOOP).json()
    assert j["settings"]["elevation_source"] == "auto"
    assert flat.get(LOOP + "&elevation_source=bogus").status_code == 400
    assert "elevation_source" in flat.get(LOOP + "&elevation_source=bogus").json()["detail"]
    r = flat.get(LOOP + "&elevation_source=dem").json()
    assert r["settings"]["elevation_source"] == "dem"
    assert r["routes"] and all(x["stats"]["elevation_source"] == "dem" and x["stats"]["ascent_m"] == 0.0
                               and set(x["elevations"]) <= {50.0} for x in r["routes"])
    a = flat.get(LOOP).json()                                   # auto: tile covers the whole loop -> dem
    assert {x["stats"]["elevation_source"] for x in a["routes"]} == {"dem"}
    b = flat.get(LOOP + "&elevation_source=brouter").json()     # same cached candidates, BRouter elevations intact
    assert b["cached"] and all(x["stats"]["elevation_source"] == "brouter" and x["stats"]["ascent_m"] > 0
                               for x in b["routes"])
    n = none.get(LOOP).json()
    assert {x["stats"]["elevation_source"] for x in n["routes"]} == {"brouter"}


def test_service_rejects_bad_source():
    svc = PlannerService.create("ireland", client=Hilly(), dem=Dem(paths=[])) if (
        FLOW_DIR / "ireland.index.csv").exists() else None
    if svc is None:
        pytest.skip("flow index missing")
    with pytest.raises(ServiceError):
        svc.resolve_settings({"elevation_source": "x"})
    assert svc.resolve_settings({}).elevation_source == "auto"


@needs_index
def test_gpx_export_carries_dem_elevations(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    svc = flow_mcp.build_service(Hilly(), make_dem(tmp_path, hill=False))
    flow_mcp.set_service(svc)
    try:
        text = flow_mcp.plan_route("loop", "53.2990,-6.2825", length_km=45, bearings=4, n=2)
        rid = text.split("\n")
        rid = next(ln.split("|")[2].strip() for ln in rid if ln.startswith("| 1 |"))
        msg = flow_mcp.export_gpx(rid, out_dir=str(out))
        assert "with dem elevation" in msg
        pts = gpxpy.parse(next(out.glob("*.gpx")).read_text()).tracks[0].segments[0].points
        assert len(pts) > 2 and all(p.elevation == 50.0 for p in pts)
        bad = flow_mcp.plan_route("loop", "53.2990,-6.2825", length_km=45, bearings=4, n=1,
                                  settings={"elevation_source": "nope"})
        assert bad.startswith("Error")
    finally:
        flow_mcp.set_service(None)
