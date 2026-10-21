#!/usr/bin/env python3
"""Reference implementation of the single-profile core of the climb-derivation spec
(docs/research/climbs.md, section Derivation approach, steps 4-7). Input: a profile CSV from
scripts/elevation_profile.py (columns distance_m, elevation_m on a 25 m grid).

Usage: uv run python scripts/climb_spec_dryrun.py data/samples/wicklow_gap_profile_glo30.csv
The implementation (and the spec's threshold constants) live in scripts/flowplan/climbs.py.
"""
import csv
import sys

import numpy as np
from flowplan.climbs import (
    MIN_GAIN,
    MIN_GRAD,
    MIN_LEN,
    MIN_POINTS,
    ascents,
    category,
    median3,
    merge,
    points,
    trim,
    zigzag,
)


def stats(d, z, s, e, label):
    length = d[e] - d[s]; gain = z[e] - z[s]
    avg = gain / length * 100 if length else 0
    pts = points(d, z, s, e)
    cat = category(pts)
    ok = length >= MIN_LEN and gain >= MIN_GAIN and avg >= MIN_GRAD and pts >= MIN_POINTS
    print(f"{label:34s} {d[s]:6.0f}-{d[e]:6.0f} m  len {length:6.0f}  z {z[s]:6.1f}->{z[e]:6.1f}  gain {gain:6.1f}  "
          f"avg {avg:5.2f}%  points {pts:6.1f}  cat {cat:>4s}  {'ACCEPT' if ok else 'REJECT'}")
    return ok


def main():
    with open(sys.argv[1]) as f:
        rows = list(csv.DictReader(f))
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
