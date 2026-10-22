import math
from pathlib import Path

import numpy as np
import pytest
import rasterio
from flowplan.terrain import Dem, climb_via_points, flat_via_points
from rasterio.transform import from_origin

REAL_TILE = Path(__file__).resolve().parents[1] / "data" / "dem" / "glo30_N53_W007.tif"
needs_tile = pytest.mark.skipif(not REAL_TILE.exists(), reason="GLO-30 tile missing")

# synthetic raster: lon -7..-6, lat 53..54 at ~0.002 deg cells, flat 50 m with a Gaussian hill (+400 m) at (-6.5, 53.5)
HILL = (-6.5, 53.5)
START = (-6.5, 53.4)     # about 11 km south of the hill


def make_dem(tmp_path, hill=True, void_north=False):
    step = 0.002
    n = int(1 / step)
    lons = -7 + (np.arange(n) + 0.5) * step
    lats = 54 - (np.arange(n) + 0.5) * step
    LO, LA = np.meshgrid(lons, lats)
    z = np.full((n, n), 50.0, dtype="float32")
    if hill:
        d2 = ((LO - HILL[0]) * 66000) ** 2 + ((LA - HILL[1]) * 111000) ** 2
        z += 400 * np.exp(-d2 / (2 * 2500.0 ** 2))
    if void_north:
        z[LA > 53.6] = -32768
    p = tmp_path / "hill.tif"
    with rasterio.open(p, "w", driver="GTiff", height=n, width=n, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(-7, 54, step, step)) as ds:
        ds.write(z, 1)
    return Dem(paths=[p])


@needs_tile
def test_real_tile_samples():
    dem = Dem()
    # the brief's (-6.410, 53.027) is a hillside at ~670 m; the actual R756 summit is at (-6.3965, 53.0418)
    wg = dem.sample(-6.3965, 53.0418)
    assert wg is not None and 440 <= wg <= 520
    assert dem.sample(-6.410, 53.027) > 600
    bay = dem.sample(-6.15, 53.33)
    assert bay is not None and bay <= 5
    w, s, e, n = dem.coverage()
    assert w <= -6.99 and e >= -6.0 and s <= 53.001 and n >= 54.0


@needs_tile
def test_outside_coverage_is_none():
    dem = Dem()
    assert dem.sample(-6.0, 55.0) is None
    assert dem.sample(10.0, 10.0) is None
    assert np.isnan(dem.sample_many([10.0], [10.0])[0])


def test_no_tiles(tmp_path):
    dem = Dem(dem_dir=tmp_path)
    assert dem.coverage() is None and dem.sample(-6.5, 53.5) is None


def test_synthetic_sampling_and_void_fallback(tmp_path):
    dem = make_dem(tmp_path, void_north=True)
    assert dem.sample(*HILL) == pytest.approx(450, abs=2)
    assert dem.sample(-6.5, 53.8) is None     # void cell -> None, no SRTM layer to fall back on
    assert dem.sample(-6.5, 54.5) is None     # outside the raster


def test_climb_points_on_hill(tmp_path):
    dem = make_dem(tmp_path)
    vp = climb_via_points(dem, START, 8000)
    assert len(vp) == 24 and not vp.coverage_note
    scores = [p.score for p in vp]
    assert scores == sorted(scores, reverse=True)
    top = vp[0]
    assert abs(top.lat - HILL[1]) < 0.06 and abs(top.lon - HILL[0]) < 0.06
    assert top.ele > 200 and top.heading_deg in (0.0, 15.0, 345.0)
    # all but one-ish of the top points are on the hill side (north)
    assert sum(1 for p in vp[:6] if p.lat > START[1]) == 6


def test_flat_points_off_hill(tmp_path):
    dem = make_dem(tmp_path)
    vp = flat_via_points(dem, START, 8000)
    assert vp[0].score == pytest.approx(0.0, abs=1.0) or vp[0].score > -5
    assert all(p.score <= 0 for p in vp)
    def hill_d(p):
        return math.hypot((p.lon - HILL[0]) * 66000, (p.lat - HILL[1]) * 111000)
    assert min(hill_d(p) for p in vp[:6]) > 4000
    assert vp[0].ele < 60


def test_void_points_skipped_and_counted(tmp_path):
    dem = make_dem(tmp_path, void_north=True)
    vp = climb_via_points(dem, (-6.5, 53.5), 15000)
    assert vp.skipped > 0 and "no DEM elevation" in vp.coverage_note
    assert all(not math.isnan(p.ele) for p in vp)
