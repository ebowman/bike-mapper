"""DEM sampling and climb-seeking / flat via-point strategy (bead 41w.4).

Dem loads every raster found under data/dem (Copernicus GLO-30 GeoTIFFs first, then SRTM .hgt/.tif in
data/dem/srtm) lazily, caches the pixel arrays, and samples nearest-cell elevations. Priority per point:
GLO-30 > SRTM; a cell that is void (NaN or <= VOID_BELOW) falls through to the next source. Outside every
source's bounds sample() returns None. No tiles are downloaded; coverage() reports the union bbox.

climb_via_points() scans a polar grid around the start (headings x radii) and ranks points by
    score = max(0, ele - ele_start) + 0.5 * relief      (relief = max - min of 4 samples 500 m N/E/S/W)
It finds high, rough ground near the start, not catalogued climbs. flat_via_points() uses the same grid
but scores -(relief + |ele - ele_start|), so the flattest, start-level ground ranks first. For both,
a higher score is better. Points with no elevation are skipped and counted in the result's coverage_note.
"""
from __future__ import annotations

import math
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer

from .scoring import REGION_CRS

__all__ = ["RELIEF_M", "VOID_BELOW", "Dem", "ViaList", "ViaPoint", "climb_via_points", "flat_via_points"]

VOID_BELOW = -100.0   # nodata is None in the GLO-30 tile; SRTM voids are -32768; sea is ~0 so -100 is safe
RELIEF_M = 500.0
DEFAULT_DEM_DIR = Path(__file__).resolve().parents[2] / "data" / "dem"


class _Source:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._arr = None
        with rasterio.open(path) as ds:
            self.bounds = tuple(ds.bounds)          # left, bottom, right, top
            self.shape = (ds.height, ds.width)
            self.transform = ds.transform
            self.nodata = ds.nodata
            self.is_geographic = ds.crs is None or ds.crs.is_geographic

    def array(self) -> np.ndarray:
        with self._lock:
            if self._arr is None:
                with rasterio.open(self.path) as ds:
                    a = ds.read(1).astype("float32")
                if self.nodata is not None:
                    a[a == self.nodata] = np.nan
                a[a <= VOID_BELOW] = np.nan
                self._arr = a
            return self._arr

    def sample(self, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
        """Nearest-cell values, NaN outside bounds or on voids."""
        l, b, r, t = self.bounds
        out = np.full(lons.shape, np.nan, dtype="float64")
        inside = (lons >= l) & (lons < r) & (lats > b) & (lats <= t)
        if not inside.any():
            return out
        a = self.array()
        tr = self.transform
        cols = np.floor((lons[inside] - tr.c) / tr.a).astype(int)
        rows = np.floor((lats[inside] - tr.f) / tr.e).astype(int)
        ok = (cols >= 0) & (cols < a.shape[1]) & (rows >= 0) & (rows < a.shape[0])
        vals = np.full(cols.shape, np.nan)
        vals[ok] = a[rows[ok], cols[ok]]
        out[inside] = vals
        return out


class Dem:
    """Multi-tile DEM. Sources: dem_dir/*.tif (GLO-30, first) then dem_dir/srtm/*.hgt|*.tif (fallback)."""

    def __init__(self, dem_dir=None, paths=None):
        self.dem_dir = Path(dem_dir) if dem_dir else DEFAULT_DEM_DIR
        self._paths = [Path(p) for p in paths] if paths is not None else None
        self._sources: list[_Source] | None = None
        self._lock = threading.Lock()

    @property
    def sources(self) -> list[_Source]:
        with self._lock:
            if self._sources is None:
                if self._paths is not None:
                    paths = self._paths
                else:
                    paths = sorted(self.dem_dir.glob("*.tif")) + sorted(
                        [*(self.dem_dir / "srtm").glob("*.hgt"), *(self.dem_dir / "srtm").glob("*.tif")])
                srcs = []
                for p in paths:
                    try:
                        srcs.append(_Source(p))
                    except (rasterio.errors.RasterioIOError, OSError):
                        continue    # unreadable file: skip; coverage() shows what loaded
                self._sources = srcs
            return self._sources

    def coverage(self):
        """Union bbox (west, south, east, north) of all loaded tiles, or None when there are none."""
        s = self.sources
        if not s:
            return None
        return (min(x.bounds[0] for x in s), min(x.bounds[1] for x in s),
                max(x.bounds[2] for x in s), max(x.bounds[3] for x in s))

    def sample_many(self, lons, lats) -> np.ndarray:
        """Elevations (m) as float array, NaN where no source has a valid value."""
        lons = np.asarray(lons, dtype="float64")
        lats = np.asarray(lats, dtype="float64")
        out = np.full(lons.shape, np.nan)
        for src in self.sources:
            miss = np.isnan(out)
            if not miss.any():
                break
            out[miss] = src.sample(lons[miss], lats[miss])
        return out

    def sample(self, lon: float, lat: float) -> float | None:
        v = float(self.sample_many(np.array([lon]), np.array([lat]))[0])
        return None if math.isnan(v) else v


DEM_COVERAGE_MIN = 0.95   # 'auto' elevation source: DEM when >= this share of route points has a DEM value


def dem_route_elevations(dem: Dem, geometry) -> tuple[list | None, float]:
    """(elevations parallel to geometry, coverage). Elevations come from DEM samples at the geometry points;
    points without a DEM value are filled by linear interpolation over distance. coverage = share of points
    that had a DEM value (0..1). Returns (None, 0.0) when no point is covered."""
    from .climbs import _cum_dist, _fill
    if len(geometry) < 2:
        return None, 0.0
    arr = np.asarray(geometry, dtype="float64")
    z = dem.sample_many(arr[:, 0], arr[:, 1])
    ok = ~np.isnan(z)
    cov = float(ok.mean())
    if not ok.any():
        return None, 0.0
    d = _cum_dist(geometry) + np.arange(len(geometry)) * 1e-9
    filled = _fill(d, [float(v) if k else None for v, k in zip(z, ok, strict=True)])
    return [float(v) for v in filled], cov


@dataclass
class ViaPoint:
    lon: float
    lat: float
    ele: float
    score: float
    heading_deg: float
    radius_m: float


class ViaList(list):
    """list[ViaPoint] plus .coverage_note ('' when every grid point had an elevation) and .skipped."""
    coverage_note: str = ""
    skipped: int = 0
    total: int = 0


def _grid(dem: Dem, start, radius_m, headings, radii, region, flat):
    sx_lon, sx_lat = float(start[0]), float(start[1])
    tf = Transformer.from_crs("EPSG:4326", REGION_CRS[region], always_xy=True)
    inv = Transformer.from_crs(REGION_CRS[region], "EPSG:4326", always_xy=True)
    sx, sy = tf.transform(sx_lon, sx_lat)
    ele0 = dem.sample(sx_lon, sx_lat)
    hs = np.array([i * 360.0 / headings for i in range(headings)])
    rs = np.array([radius_m * f for f in radii])
    H, R = np.meshgrid(hs, rs)
    H, R = H.ravel(), R.ravel()
    th = np.radians(H)
    x, y = sx + R * np.sin(th), sy + R * np.cos(th)
    lon, lat = inv.transform(x, y)
    lon, lat = np.asarray(lon), np.asarray(lat)
    ele = dem.sample_many(lon, lat)
    rel_samples = []
    for dx, dy in ((0, RELIEF_M), (RELIEF_M, 0), (0, -RELIEF_M), (-RELIEF_M, 0)):
        lo2, la2 = inv.transform(x + dx, y + dy)
        rel_samples.append(dem.sample_many(np.asarray(lo2), np.asarray(la2)))
    stack = np.vstack([ele, *rel_samples])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)   # all-NaN columns (void/outside) are skipped by the caller
        relief = np.nanmax(stack, axis=0) - np.nanmin(stack, axis=0)
    return ele0, H, R, lon, lat, ele, relief


def _via_points(dem, start, radius_m, n, headings, radii, region, flat) -> ViaList:
    if region not in REGION_CRS:
        raise ValueError(f"unknown region {region!r}; known: {', '.join(REGION_CRS)}")
    ele0, H, R, lon, lat, ele, relief = _grid(dem, start, radius_m, headings, radii, region, flat)
    out = ViaList()
    out.total = len(H)
    if ele0 is None:
        out.skipped = len(H)
        out.coverage_note = f"start has no DEM elevation: all {len(H)} grid points skipped"
        return out
    pts = []
    for i in range(len(H)):
        if math.isnan(ele[i]):
            out.skipped += 1
            continue
        if flat:
            score = -(float(relief[i]) + abs(float(ele[i]) - ele0))
        else:
            score = max(0.0, float(ele[i]) - ele0) + 0.5 * float(relief[i])
        pts.append(ViaPoint(float(lon[i]), float(lat[i]), float(ele[i]), score, float(H[i]), float(R[i])))
    pts.sort(key=lambda p: -p.score)
    out.extend(pts[:n])
    if out.skipped:
        out.coverage_note = f"{out.skipped} of {len(H)} grid points have no DEM elevation (outside coverage or void)"
    return out


def climb_via_points(dem: Dem, start, radius_m, n=24, headings=24, radii=(0.5, 0.85, 1.2),
                     region: str = "ireland") -> ViaList:
    """Top-n grid points by climb score (highest first). radius_m is the nominal ring radius."""
    return _via_points(dem, start, radius_m, n, headings, radii, region, flat=False)


def flat_via_points(dem: Dem, start, radius_m, n=24, headings=24, radii=(0.5, 0.85, 1.2),
                    region: str = "ireland") -> ViaList:
    """Top-n grid points by flatness: score = -(relief + |ele - ele_start|), so the flattest rank first."""
    return _via_points(dem, start, radius_m, n, headings, radii, region, flat=True)
