#!/usr/bin/env python3
"""Reference implementation of the single-profile core of the climb-derivation spec
(docs/research/climbs.md, section Derivation approach, steps 4-7). Input: a profile CSV from
scripts/elevation_profile.py (columns distance_m, elevation_m on a 25 m grid).

Usage: uv run python scripts/climb_spec_dryrun.py data/samples/wicklow_gap_profile_glo30.csv
All constants below are the spec's thresholds.
"""
import csv
import sys
import numpy as np

STEP = 25.0       # m, sample spacing
H = 5.0           # m, swing needed to confirm a turning point (zigzag)
MERGE_LOSS = 10.0     # m, max descent between two ascents to merge them
MERGE_LEN = 400.0     # m, max descent length to merge
TRIM_WIN = 300.0      # m, leading/trailing window tested for flatness
TRIM_GRAD = 2.5       # %, window average below this is trimmed
TRIM_STEP = 100.0     # m, trim granularity
MIN_AFTER_TRIM = 600.0  # m, trimming never leaves a climb shorter than this
MIN_LEN, MIN_GAIN, MIN_GRAD, MIN_POINTS = 500.0, 30.0, 3.0, 25.0
SEC = 100.0           # m, scoring section
GCAP = 25.0           # %, section gradient cap
CATS = [(1500, "SHC"), (900, "HC"), (600, "1"), (300, "2"), (150, "3"), (75, "4"), (25, "5")]


def median3(z):
    o = z.copy()
    for i in range(1, len(z) - 1):
        o[i] = np.median(z[i - 1:i + 2])
    return o


def zigzag(z):
    """Indices of alternating local minima/maxima; a turning point is confirmed once the profile
    moves H metres away from it."""
    ext, direction, hi, lo = [], 0, 0, 0
    for i in range(1, len(z)):
        if direction >= 0 and z[i] > z[hi]: hi = i
        if direction <= 0 and z[i] < z[lo]: lo = i
        if direction == 0:
            if z[i] - z[lo] >= H: ext.append(lo); direction = 1; hi = i
            elif z[hi] - z[i] >= H: ext.append(hi); direction = -1; lo = i
        elif direction == 1:
            if z[hi] - z[i] >= H: ext.append(hi); direction = -1; lo = i
        else:
            if z[i] - z[lo] >= H: ext.append(lo); direction = 1; hi = i
    ext.append(hi if direction >= 0 else lo)
    return ext


def ascents(z, ext):
    """(start_idx, end_idx) for each min->max pair of consecutive extrema."""
    out = []
    for a, b in zip(ext[:-1], ext[1:]):
        if z[b] > z[a]:
            out.append([a, b])
    return out


def merge(z, asc):
    m = [asc[0][:]]
    for a, b in asc[1:]:
        pa, pb = m[-1]
        loss = z[pb] - z[a]
        dlen = (a - pb) * STEP
        if loss <= MERGE_LOSS and dlen <= MERGE_LEN:
            m[-1][1] = b if z[b] >= z[pb] else pb
        else:
            m.append([a, b])
    return m


def sections(d, z, s, e):
    pts = []
    pos = d[s]
    while pos < d[e] - 1e-6:
        nxt = min(pos + SEC, d[e])
        g = (np.interp(nxt, d, z) - np.interp(pos, d, z)) / (nxt - pos) * 100.0
        pts.append((pos, nxt, g))
        pos = nxt
    return pts


def points(d, z, s, e):
    tot = 0.0
    for a, b, g in sections(d, z, s, e):
        g = max(min(g, GCAP), 0.0)
        tot += g * g / 10.0 * (b - a) / SEC
    return tot


def trim(d, z, s, e):
    w = int(TRIM_WIN / STEP); st = int(TRIM_STEP / STEP)
    while (e - s - st) * STEP >= MIN_AFTER_TRIM and (z[s + w] - z[s]) / (w * STEP) * 100 < TRIM_GRAD:
        s += st
    while (e - s - st) * STEP >= MIN_AFTER_TRIM and (z[e] - z[e - w]) / (w * STEP) * 100 < TRIM_GRAD:
        e -= st
    return s, e


def stats(d, z, s, e, label):
    length = d[e] - d[s]; gain = z[e] - z[s]
    avg = gain / length * 100 if length else 0
    pts = points(d, z, s, e)
    cat = next((c for t, c in CATS if pts >= t), "none")
    ok = length >= MIN_LEN and gain >= MIN_GAIN and avg >= MIN_GRAD and pts >= MIN_POINTS
    print(f"{label:34s} {d[s]:6.0f}-{d[e]:6.0f} m  len {length:6.0f}  z {z[s]:6.1f}->{z[e]:6.1f}  gain {gain:6.1f}  "
          f"avg {avg:5.2f}%  points {pts:6.1f}  cat {cat:>4s}  {'ACCEPT' if ok else 'REJECT'}")
    return ok


def main():
    rows = list(csv.DictReader(open(sys.argv[1])))
    d = np.array([float(r["distance_m"]) for r in rows]); z0 = np.array([float(r["elevation_m"]) for r in rows])
    z = median3(z0)
    ext = zigzag(z)
    print("extrema (m, elev):", [(int(d[i]), round(float(z[i]), 1)) for i in ext])
    asc = merge(z, ascents(z, ext))
    print("naive whole track:")
    stats(d, z, 0, len(d) - 1, "  start-to-end, no trimming")
    print("spec candidates:")
    for s, e in asc:
        stats(d, z, s, e, "  pre-trim ascent")
        s2, e2 = trim(d, z, s, e)
        stats(d, z, s2, e2, "  post-trim (spec result)")
        if s2 > s:
            stats(d, z, s, s2, "  removed leading approach")


if __name__ == "__main__":
    main()
