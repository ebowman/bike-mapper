"""Turn and straightness metrics for a route geometry.

A turn is a heading change >= TURN_DEG between the direction of travel ~WINDOW_M before and
~WINDOW_M after a vertex (projected coordinates). Turn vertices within CLUSTER_M of each other
(chained) count once (S-bends at one junction). With BRouter message segments, only turn vertices
within CLUSTER_M of a junction (the start of a segment BRouter charged turn_cost >= min_turn_cost on) are kept (geometry gives the
angle); without any such charge the geometry alone decides. An uninterrupted stretch is the distance
between consecutive interruptions (a turn, or a stop hit with p >= stop_p_threshold).
"""
from __future__ import annotations

import itertools
import math

import numpy as np
from pyproj import Transformer

from .scoring import REGION_CRS

WINDOW_M = 15.0
TURN_DEG = 30.0
SHARP_DEG = 60.0
CLUSTER_M = 25.0


def _point_at(xy, cum, d):
    """Interpolated point at distance d along the polyline."""
    d = min(max(d, 0.0), cum[-1])
    j = int(np.searchsorted(cum, d, side="right")) - 1
    j = min(max(j, 0), len(xy) - 2)
    seg = cum[j + 1] - cum[j]
    t = 0.0 if seg <= 0 else (d - cum[j]) / seg
    return xy[j] + t * (xy[j + 1] - xy[j])


def _heading_change(xy, cum, i):
    """Absolute heading change in degrees at vertex i, or 0 when a side is too short."""
    v = xy[i]
    before = v - _point_at(xy, cum, cum[i] - WINDOW_M)
    after = _point_at(xy, cum, cum[i] + WINDOW_M) - v
    nb, na = math.hypot(*before), math.hypot(*after)
    if nb < 1.0 or na < 1.0:
        return 0.0
    cross = before[0] * after[1] - before[1] * after[0]
    dot = before[0] * after[0] + before[1] * after[1]
    return abs(math.degrees(math.atan2(cross, dot)))


# default BRouter turn_cost setting is 400 per 90 degrees; a bend of TURN_DEG costs ~400 * (1 - cos 30)
MIN_TURN_COST = 400.0 * (1 - math.cos(math.radians(TURN_DEG)))


def turn_metrics(geometry, segments=None, stop_hits=None, stop_p_threshold: float = 0.10,
                 region: str = "ireland", min_turn_cost: float = MIN_TURN_COST) -> dict:
    empty = {"turns": 0, "turns_per_km": 0.0, "sharp_turns": 0, "longest_straight_km": 0.0,
             "mean_straight_km": 0.0, "turn_points": []}
    pts = []
    for p in geometry:
        p = (float(p[0]), float(p[1]))
        if not pts or p != pts[-1]:
            pts.append(p)
    if len(pts) < 2:
        return empty
    tf = Transformer.from_crs("EPSG:4326", REGION_CRS[region], always_xy=True)
    x, y = tf.transform([p[0] for p in pts], [p[1] for p in pts])
    xy = np.column_stack([x, y])
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
    total = float(cum[-1])
    if total <= 0:
        return empty

    # candidate turn vertices
    cands = []
    for i in range(1, len(pts) - 1):
        a = _heading_change(xy, cum, i)
        if a >= TURN_DEG:
            cands.append((i, a))
    # BRouter charges a turn on the segment that LEAVES the junction, so the junction is that
    # segment's START (the previous segment's end; the route's first point for segment 0).
    segs = segments or []
    junctions = []
    for k, sg in enumerate(segs):
        if float(sg.get("turn_cost", 0) or 0) >= min_turn_cost:
            junctions.append((segs[k - 1]["lon"], segs[k - 1]["lat"]) if k > 0 else pts[0])
    if junctions and cands:
        jx, jy = tf.transform([j[0] for j in junctions], [j[1] for j in junctions])
        jxy = np.column_stack([jx, jy])
        cands = [(i, a) for i, a in cands
                 if np.hypot(*(jxy - xy[i]).T).min() <= CLUSTER_M]

    # cluster chained turn vertices within CLUSTER_M; keep the sharpest, positioned there
    clusters = []
    for i, a in cands:
        if clusters and cum[i] - cum[clusters[-1][-1][0]] <= CLUSTER_M:
            clusters[-1].append((i, a))
        else:
            clusters.append([(i, a)])
    turns = []
    for cl in clusters:
        i, a = max(cl, key=lambda t: t[1])
        turns.append((i, a))
    turn_points = [{"lat": pts[i][1], "lon": pts[i][0], "angle_deg": round(a, 1)} for i, a in turns]

    marks = [float(cum[i]) for i, _ in turns]
    for h in stop_hits or []:
        if float(h.get("p", 0) or 0) >= stop_p_threshold:
            marks.append(min(max(float(h.get("dist_along_km", 0) or 0) * 1000, 0.0), total))
    bounds = [0.0, *sorted(marks), total]
    stretches = [(b - a) / 1000 for a, b in itertools.pairwise(bounds)]
    return {"turns": len(turns), "turns_per_km": len(turns) / (total / 1000),
            "sharp_turns": sum(1 for _, a in turns if a > SHARP_DEG),
            "longest_straight_km": max(stretches), "mean_straight_km": sum(stretches) / len(stretches),
            "turn_points": turn_points}
