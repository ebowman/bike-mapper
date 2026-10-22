"""Ascent/descent, climb detection and climb points from a route's elevation profile.

Implements the climb-derivation spec in docs/research/climbs.md (steps 4-7) on a route given
as (lon, lat) coordinates plus parallel elevations (as in Candidate.geometry / .elevations).

Pipeline (detect_climbs):
  1. Missing elevations (None) are filled by linear interpolation over cumulative distance;
     leading/trailing Nones take the nearest known value. No known elevations -> no climbs.
  2. The profile is resampled to a regular STEP (25 m) grid over haversine distance, so BRouter's
     irregular node spacing does not bias grades.
  3. median3 smoothing, zigzag turning points (5 m swing), merge of ascents separated by a
     descent of <= 10 m and <= 400 m, splitting of an ascent at flat stretches > 200 m
     (< 1 % average), trimming of flat lead-in/out (< 2.5 % over 300 m),
     acceptance: length >= 500 m, gain >= 30 m, avg grade >= 3 %, points >= 25.
  Points = sum over 100 m sections of (grade clamped to 0..25 %)^2 / 10 * section_len/100.

elevation_stats uses a 3 m hysteresis filter: an anchor elevation only moves, and ascent/descent
only accrue, once the profile departs from the anchor by >= 3 m, so noise with a peak-to-peak swing under 3 m (e.g. +-1.4 m) yields 0; +-2 m (4 m swing) does count.

Wicklow Gap check (data/samples/wicklow_gap_profile_glo30.csv, GLO-30 DEM on a 25 m grid; the
GPX sample has no <ele>), library vs spec (docs/research/climbs.md):
  length 6,575 m (spec 6,575), gain 332.1 m (spec 332), avg grade 5.05 % (spec 5.05),
  points 204.0 (spec 204; ClimbFinder 6.8 km / 337 m / 4.9 % / 202 pts), category 3.
BRouter elevations are ~1 m-resolution SRTM-derived heights and coarser than GLO-30, so expect
gain/points on real BRouter routes to deviate by roughly 10-20 % from DEM-profile values.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np

from .scoring import haversine_m

STEP = 25.0       # m, resample spacing
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
FLAT_GAP = 200.0      # m, a flat stretch (< FLAT_GRAD) longer than this splits an ascent in two
FLAT_GRAD = 1.0       # %
HYST = 3.0            # m, hysteresis for ascent/descent on BRouter elevations
DEM_HYST = 10.0       # m, hysteresis on DEM-sampled elevations (41w.14: 3 m inflates flat routes 4x)


@dataclass
class Climb:
    start_km: float
    end_km: float
    length_m: float
    gain_m: float
    avg_grade_pct: float
    max_500m_grade_pct: float
    points: float
    category: str


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
        if direction >= 0 and z[i] > z[hi]:
            hi = i
        if direction <= 0 and z[i] < z[lo]:
            lo = i
        if direction == 0:
            if z[i] - z[lo] >= H:
                ext.append(lo); direction = 1; hi = i
            elif z[hi] - z[i] >= H:
                ext.append(hi); direction = -1; lo = i
        elif direction == 1:
            if z[hi] - z[i] >= H:
                ext.append(hi); direction = -1; lo = i
        else:
            if z[i] - z[lo] >= H:
                ext.append(lo); direction = 1; hi = i
    ext.append(hi if direction >= 0 else lo)
    return ext


def ascents(z, ext):
    """(start_idx, end_idx) for each min->max pair of consecutive extrema."""
    return [[a, b] for a, b in itertools.pairwise(ext) if z[b] > z[a]]


def merge(z, asc):
    if not asc:
        return []
    m = [asc[0][:]]
    for a, b in asc[1:]:
        _, pb = m[-1]
        loss = z[pb] - z[a]
        dlen = (a - pb) * STEP
        if loss <= MERGE_LOSS and dlen <= MERGE_LEN:
            m[-1][1] = b if z[b] >= z[pb] else pb
        else:
            m.append([a, b])
    return m


def split_flats(z, s, e):
    """Split ascent [s, e] around interior flat stretches longer than FLAT_GAP (average grade
    < FLAT_GRAD over a >FLAT_GAP window). The zigzag step only breaks at descents, so a long
    plateau would otherwise glue two climbs together. Returns a list of [start, end] pieces."""
    k = int(FLAT_GAP / STEP) + 1
    flat = [False] * (e - s)
    for i in range(s, e - k + 1):
        if (z[i + k] - z[i]) / (k * STEP) * 100.0 < FLAT_GRAD:
            for j in range(i, i + k):
                flat[j - s] = True
    pieces, start, i = [], s, 0
    while i < e - s:
        if flat[i]:
            j = i
            while j < e - s and flat[j]:
                j += 1
            if i > start - s:
                pieces.append([start, s + i])
            start = s + j
            i = j
        else:
            i += 1
    if e > start:
        pieces.append([start, e])
    return pieces


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


def category(pts: float) -> str:
    return next((c for t, c in CATS if pts >= t), "none")


def max_window_grade(d, z, s, e, win=500.0) -> float:
    """Steepest average grade (%) over any `win`-metre window inside [s, e] (whole climb if shorter)."""
    k = round(win / STEP)
    k = min(k, e - s)
    if k <= 0:
        return 0.0
    return float(max((z[i + k] - z[i]) / (d[i + k] - d[i]) * 100.0 for i in range(s, e - k + 1)))


def climb_from_profile(d, z, s, e) -> Climb | None:
    """Evaluate profile slice [s, e]; return a Climb if it passes the spec thresholds, else None."""
    length = float(d[e] - d[s]); gain = float(z[e] - z[s])
    if length <= 0:
        return None
    avg = gain / length * 100.0
    pts = points(d, z, s, e)
    if not (length >= MIN_LEN and gain >= MIN_GAIN and avg >= MIN_GRAD and pts >= MIN_POINTS):
        return None
    return Climb(float(d[s]) / 1000.0, float(d[e]) / 1000.0, length, gain, avg,
                 max_window_grade(d, z, s, e), float(pts), category(pts))


def detect_on_profile(d, z0) -> list[Climb]:
    """Spec detection on a profile already on the STEP grid (d, z0 numpy arrays)."""
    if len(d) < 3:
        return []
    z = median3(np.asarray(z0, dtype=float))
    asc = merge(z, ascents(z, zigzag(z)))
    out = []
    for s0, e0 in asc:
        for s, e in split_flats(z, s0, e0):
            if e - s < 2:
                continue
            s2, e2 = trim(d, z, s, e)
            c = climb_from_profile(d, z, s2, e2)
            if c:
                out.append(c)
    return out


def _cum_dist(coords) -> np.ndarray:
    cum = [0.0]
    for a, b in itertools.pairwise(coords):
        cum.append(cum[-1] + haversine_m(a[0], a[1], b[0], b[1]))
    return np.array(cum)


def _fill(d: np.ndarray, elevations):
    """Linearly interpolate None elevations over distance. Returns (d, z) or None if nothing known."""
    known = [i for i, v in enumerate(elevations) if v is not None]
    if not known:
        return None
    z = np.interp(d, d[known], [float(elevations[i]) for i in known])
    return z


def resample(coords, elevations):
    """(d, z) on a regular STEP grid in metres, or None when unusable (<2 distinct points / no ele)."""
    n = min(len(coords), len(elevations))
    if n < 2:
        return None
    coords, elevations = coords[:n], elevations[:n]
    d = _cum_dist(coords)
    # np.interp needs increasing x: drop coincident points (keep the first of each run)
    idx = [0]
    for i in range(1, n):
        if d[i] > d[idx[-1]] + 1e-9:
            idx.append(i)
    if len(idx) < 2:
        return None
    d = d[idx]; elevations = [elevations[i] for i in idx]
    z = _fill(d, elevations)
    if z is None:
        return None
    grid = np.arange(0.0, d[-1] + 1e-9, STEP)
    return grid, np.interp(grid, d, z)


def detect_climbs(coords, elevations) -> list[Climb]:
    """Climbs (spec thresholds) along a route; coords are (lon, lat), elevations parallel (None ok)."""
    r = resample(coords, elevations)
    if r is None:
        return []
    return detect_on_profile(*r)


def elevation_stats(coords, elevations, hyst: float = HYST) -> dict:
    """{ascent_m, descent_m, max_ele, min_ele}. None elevations are interpolated over distance.
    Ascent/descent use a hysteresis filter, 3 m by default (see module docstring). max/min are None if no
    elevation is known."""
    n = min(len(coords), len(elevations))
    if n == 0 or all(v is None for v in elevations[:n]):
        return {"ascent_m": 0.0, "descent_m": 0.0, "max_ele": None, "min_ele": None}
    d = _cum_dist(coords[:n])
    # strictly-increasing x not required for the known points only if duplicates are tolerated;
    # nudge duplicates so np.interp stays well-defined
    d = d + np.arange(n) * 1e-9
    z = _fill(d, elevations[:n])
    anchor = z[0]; up = down = 0.0
    for v in z[1:]:
        if v - anchor >= hyst:
            up += v - anchor; anchor = v
        elif anchor - v >= hyst:
            down += anchor - v; anchor = v
    return {"ascent_m": float(up), "descent_m": float(down),
            "max_ele": float(z.max()), "min_ele": float(z.min())}


def climb_score(climbs) -> dict:
    """{score: sum of points, hardest: Climb with most points (or None), n_climbs}."""
    return {"score": float(sum(c.points for c in climbs)),
            "hardest": max(climbs, key=lambda c: c.points, default=None),
            "n_climbs": len(climbs)}
