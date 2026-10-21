"""Elevation profile of a GPX track sampled from a DEM (bead dhy.3).

Resamples the track every --step metres along the geodesic (WGS84), samples the DEM with
manual bilinear interpolation from the 4 surrounding cell centres, then reports total
ascent (raw sum of positive steps and 3 m hysteresis), average gradient, and the max
gradient over --window metre windows. Writes distance/elevation/gradient CSV.

Samples whose 4 neighbour cells include no-data/void are logged to stderr and skipped
(never propagated as NaN into the statistics); the profile continues across the gap.

Usage:
  uv run python scripts/elevation_profile.py --gpx data/samples/wicklow_gap_r756.gpx \
      --dem data/dem/glo30_N53_W007.tif --label glo30 [--step 25] [--window 100] [--out csv]
--dem may be a local GeoTIFF/.hgt or an https URL (read via GDAL /vsicurl/).
Default --out: data/samples/wicklow_gap_profile_<label>.csv (label defaults to DEM file stem).
"""
import argparse
import csv
import itertools
import math
import os
import sys

import gpxpy
import numpy as np
import rasterio
from pyproj import Geod, Transformer

GEOD = Geod(ellps="WGS84")
VOID_BELOW = -500.0  # belt and braces: SRTM voids are -32768


def load_track(path):
    with open(path) as f:
        g = gpxpy.parse(f)
    pts = [(p.latitude, p.longitude) for t in g.tracks for s in t.segments for p in s.points]
    if not pts:
        pts = [(p.latitude, p.longitude) for r in g.routes for p in r.points]
    if len(pts) < 2:
        sys.exit(f"{path}: fewer than 2 track points")
    return pts


def resample(pts, step):
    """Return (dist_m, lat, lon) arrays at every `step` m along the geodesic polyline."""
    d_out, la_out, lo_out = [], [], []
    cum = 0.0   # distance at start of current segment
    next_d = 0.0
    total = 0.0
    segs = []
    for (la1, lo1), (la2, lo2) in itertools.pairwise(pts):
        az, _, dist = GEOD.inv(lo1, la1, lo2, la2)
        segs.append((la1, lo1, az, dist))
        total += dist
    for la1, lo1, az, dist in segs:
        while next_d <= cum + dist + 1e-9 and next_d <= total + 1e-9:
            lo, la, _ = GEOD.fwd(lo1, la1, az, max(next_d - cum, 0.0))
            d_out.append(next_d); la_out.append(la); lo_out.append(lo)
            next_d += step
        cum += dist
    return np.array(d_out), np.array(la_out), np.array(lo_out), total


def bilinear(ds, lons, lats):
    """Bilinear sample band 1; returns array with NaN where any of the 4 cells is no-data/outside."""
    if ds.crs and not ds.crs.is_geographic:
        x, y = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True).transform(lons, lats)
    else:
        x, y = lons, lats
    inv = ~ds.transform
    out = np.full(len(lons), np.nan)
    reason = [""] * len(lons)
    for i, (xi, yi) in enumerate(zip(x, y)):
        c, r = inv * (xi, yi)       # continuous pixel coords, cell centre of col j at j+0.5
        c -= 0.5; r -= 0.5
        c0, r0 = math.floor(c), math.floor(r)
        if c0 < 0 or r0 < 0 or c0 + 1 >= ds.width or r0 + 1 >= ds.height:
            reason[i] = "outside DEM"; continue
        win = rasterio.windows.Window(c0, r0, 2, 2)
        a = ds.read(1, window=win, masked=True)
        if np.ma.is_masked(a) and np.ma.getmaskarray(a).any():
            reason[i] = "no-data neighbour"; continue
        v = np.ma.getdata(a).astype(float)
        if (v < VOID_BELOW).any() or np.isnan(v).any():
            reason[i] = "void neighbour"; continue
        fx, fy = c - c0, r - r0
        out[i] = (v[0, 0]*(1-fx)*(1-fy) + v[0, 1]*fx*(1-fy) + v[1, 0]*(1-fx)*fy + v[1, 1]*fx*fy)
    return out, reason


def ascent_hysteresis(z, thr):
    """Total ascent counting a rise only once it exceeds `thr` m above the last low point."""
    asc, low, high, rising = 0.0, z[0], z[0], False
    for v in z[1:]:
        if rising:
            if v > high:
                high = v
            elif high - v >= thr:      # turned down: bank the climb
                asc += high - low
                rising, low = False, v
        else:
            if v < low:
                low = v
            elif v - low >= thr:       # turned up
                rising, high = True, v
    if rising:
        asc += high - low
    return asc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gpx", required=True)
    ap.add_argument("--dem", required=True, help="GeoTIFF/.hgt path or https URL")
    ap.add_argument("--step", type=float, default=25.0)
    ap.add_argument("--window", type=float, default=100.0)
    ap.add_argument("--hysteresis", type=float, default=3.0)
    ap.add_argument("--tail-m", type=float, help="only use the last N metres of the track (to match a reference climb that starts higher up)")
    ap.add_argument("--label", help="DEM label for the default CSV name")
    ap.add_argument("--out")
    a = ap.parse_args()

    label = a.label or os.path.splitext(os.path.basename(a.dem))[0]
    out = a.out or f"data/samples/wicklow_gap_profile_{label}.csv"
    src = "/vsicurl/" + a.dem if a.dem.startswith("http") else a.dem
    pts = load_track(a.gpx)
    d, la, lo, total = resample(pts, a.step)
    if a.tail_m:
        keep = d >= total - a.tail_m
        d, la, lo = d[keep] - d[keep][0], la[keep], lo[keep]
        label += f"_tail{a.tail_m:g}"
        out = a.out or f"data/samples/wicklow_gap_profile_{label}.csv"
    with rasterio.open(src) as ds:
        z, reason = bilinear(ds, lo, la)
        print(f"DEM {a.dem}: {ds.width}x{ds.height}, crs={ds.crs}, res={ds.res}, nodata={ds.nodata}", file=sys.stderr)
    bad = [i for i in range(len(z)) if np.isnan(z[i])]
    for i in bad:
        print(f"SKIP sample {i} at {d[i]:.0f} m ({la[i]:.5f},{lo[i]:.5f}): {reason[i]}", file=sys.stderr)
    ok = ~np.isnan(z)
    if ok.sum() < 2:
        sys.exit("fewer than 2 valid samples; cannot compute profile")
    dv, zv = d[ok], z[ok]
    # gradient to previous valid sample (so a skipped gap is bridged, not zero-filled)
    grad = np.full(len(zv), np.nan)
    grad[1:] = (zv[1:] - zv[:-1]) / (dv[1:] - dv[:-1]) * 100.0
    # max gradient over `window` m: elevation change between samples ~window apart
    best, best_at = -1e9, None
    for i in range(len(dv)):
        j = int(np.searchsorted(dv, dv[i] + a.window - 1e-6))
        if j >= len(dv): break
        if abs((dv[j] - dv[i]) - a.window) > a.step * 0.5 + 1e-6:
            continue  # window straddles a skipped gap
        g = (zv[j] - zv[i]) / (dv[j] - dv[i]) * 100.0
        if g > best: best, best_at = g, dv[i]
    diffs = np.diff(zv)
    raw = float(diffs[diffs > 0].sum())
    hyst = ascent_hysteresis(list(zv), a.hysteresis)
    length = float(dv[-1] - dv[0])
    avg = (zv[-1] - zv[0]) / length * 100.0
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["distance_m", "lat", "lon", "elevation_m", "gradient_pct_to_prev"])
        for k in range(len(dv)):
            idx = np.where(ok)[0][k]
            w.writerow([f"{dv[k]:.1f}", f"{la[idx]:.6f}", f"{lo[idx]:.6f}", f"{zv[k]:.2f}",
                        "" if np.isnan(grad[k]) else f"{grad[k]:.2f}"])
    print(f"label={label} length_m={length:.0f} samples={len(dv)} skipped={len(bad)} "
          f"start_m={zv[0]:.1f} end_m={zv[-1]:.1f} max_elev_m={zv.max():.1f} net_gain_m={zv[-1]-zv[0]:.1f} "
          f"ascent_raw_m={raw:.0f} ascent_hyst{a.hysteresis:g}_m={hyst:.0f} avg_grad_pct={avg:.2f} "
          f"max_grad_{a.window:g}m_pct={best:.1f} (at {best_at:.0f} m)")
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
