"""Score a route geometry for expected stops with the validated stop model.

Matching rule: for each route segment (A, B), candidate events are index rows
whose event node lies within node_snap_m (default 1 m) of the segment; an event matches if its
from-node (previous node on the way, i.e. the arrival direction) also lies within
snap_m of the segment and is not ahead of the event node along A->B. (Testing
only the segment end points misses nodes BRouter dropped as collinear.) Events sharing (node_id, way_id, dir) are deduplicated to the highest-
precedence class (model.classes). p = model.p(cause); the index `amount` column
is ignored.

Parity check 2026-10-21
Event counts, flow_score.py (--weights combined) vs reference
scripts/score_route_stops.py --events data/osm/events_ireland.csv (reference run
with every amount set to 1 so it reports counts). Columns: signal / stop /
give_way / rb_entry / xing_signal / yield_infer / yield_equal.

  route               flow_score               reference
  dublin-baseline     18/1/1/0/15/2/38         18/1/1/0/15/2/37
  dublin-flow         12/2/1/0/8/2/35          12/2/1/0/8/2/34
  wicklow-baseline    0/1/0/0/0/1/12           0/1/0/0/0/1/12
  wicklow-flow        0/1/0/0/0/1/12           0/1/0/0/0/1/12

Exact on signal, stop, give_way, rb_entry, xing_signal; yield_equal is +1 on the
two Dublin routes (limit: 2). Fixes needed to get here: segment (not endpoint)
matching because BRouter drops collinear points; arrival edge must align with the
route (cos >= 0.5) to reject side-road from-nodes; one arrival per node per
segment; event node within node_snap_m=1 m (true hits <= 0.1 m, parallel-way
false hits >= 3 m).
"""
from __future__ import annotations

import itertools
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely import STRtree

FLOW_DIR = Path(__file__).resolve().parents[2] / "data" / "flow"
REGION_CRS = {"ireland": "EPSG:2157"}  # add e.g. "berlin": "EPSG:25833"
MIN_COS = 0.5  # the arrival edge must point roughly along the route (<= 60 deg)
CAUSES = ("signal", "stop", "give_way", "rb_entry", "xing_signal",
          "yield_infer", "yield_equal")


class FlowIndex:
    def __init__(self, df: pd.DataFrame, crs: str, load_seconds: float = 0.0):
        t0 = time.perf_counter()
        self.crs = crs
        self.tf = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        self.node_id = df["node_id"].to_numpy(np.int64)
        self.way_id = df["way_id"].to_numpy(np.int64)
        self.dir = df["dir"].to_numpy(str)
        self.cause = df["cause"].to_numpy(str)
        self.lat = df["lat"].to_numpy(float)
        self.lon = df["lon"].to_numpy(float)
        ex, ey = self.tf.transform(self.lon, self.lat)
        self.xy = np.column_stack([ex, ey])
        fx, fy = self.tf.transform(df["from_lon"].to_numpy(float),
                                   df["from_lat"].to_numpy(float))
        self.from_xy = np.column_stack([fx, fy])  # NaN where from-node missing
        self.tree = STRtree(shapely.points(self.xy))
        self.load_seconds = load_seconds + (time.perf_counter() - t0)

    def __len__(self):
        return len(self.node_id)

    @classmethod
    def load(cls, region: str = "ireland", path=None) -> FlowIndex:
        if region not in REGION_CRS:
            raise ValueError(f"unknown region {region!r}; known: {', '.join(REGION_CRS)}")
        t0 = time.perf_counter()
        df = pd.read_csv(path or FLOW_DIR / f"{region}.index.csv",
                         dtype={"node_id": np.int64, "way_id": np.int64})
        return cls(df, REGION_CRS[region], time.perf_counter() - t0)


@dataclass
class RouteScore:
    distance_km: float = 0.0
    expected_stops: float = 0.0
    expected_stop_s: float = 0.0
    stops_per_km: float = 0.0
    by_class: dict = field(default_factory=dict)
    hits: list = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371008.8 * math.asin(math.sqrt(a))


def score(points, model, index: FlowIndex, snap_m: float = 5.0,
          node_snap_m: float = 1.0) -> RouteScore:
    by_class = {c: {"events": 0, "expected": 0.0} for c in CAUSES}
    res = RouteScore(by_class=by_class)
    pts = []
    for p in points:
        p = (float(p[0]), float(p[1]))
        if not pts or p != pts[-1]:
            pts.append(p)
    res.diagnostics = {"points": len(pts), "matched_nodes": 0,
                       "weight_set": model.weight_set}
    if len(pts) < 2:
        return res
    cum = [0.0]
    for a, b in itertools.pairwise(pts):
        cum.append(cum[-1] + haversine_m(a[0], a[1], b[0], b[1]))
    res.distance_km = cum[-1] / 1000

    x, y = index.tf.transform([p[0] for p in pts], [p[1] for p in pts])
    xy = np.column_stack([x, y])
    ok = np.isfinite(xy).all(axis=1)
    rank = {c: i for i, c in enumerate(model.classes)}
    # candidates per segment (A=pts[q], B=pts[q+1]): event node within node_snap_m of
    # the segment (BRouter writes OSM node positions exactly: true hits are <= 0.1 m
    # from the route, parallel-way false hits are >= 3 m). BRouter also drops
    # near-collinear points, so intermediate nodes lie ON the segment, not at its
    # ends. The from-node must also be within snap_m of the
    # segment and not ahead of the node along the direction of travel.
    A, Bp = xy[:-1], xy[1:]
    segs = shapely.linestrings(np.stack([A, Bp], axis=1))
    qi, ti = index.tree.query(segs, predicate="dwithin", distance=node_snap_m)
    if len(qi):
        d = Bp[qi] - A[qi]
        L2 = np.maximum((d ** 2).sum(axis=1), 1e-9)
        L = np.sqrt(L2)
        fa = index.from_xy[ti]
        sn = ((index.xy[ti] - A[qi]) * d).sum(axis=1) / L   # metres along segment
        sf = ((fa - A[qi]) * d).sum(axis=1) / L
        tf = np.clip(sf / L, 0.0, 1.0)[:, None]
        dfrom = np.hypot(*(fa - (A[qi] + tf * d)).T)         # NaN from-node -> NaN
        e = index.xy[ti] - fa                                # from-node -> event node
        cosang = (e * d).sum(axis=1) / (np.maximum(np.hypot(*e.T), 1e-9) * L)
        keep = ((dfrom <= snap_m) & (sf <= sn + 0.5) & (cosang >= MIN_COS)
                & ok[qi] & ok[qi + 1])
        # A route arrives at a node once: where several (way, dir) arrivals qualify at
        # the same node on the same segment, keep the one best aligned with the route.
        qi, ti, cosang, dfrom = qi[keep], ti[keep], cosang[keep], dfrom[keep]
        order = np.lexsort((dfrom, -cosang))
        seen, sel = {}, []
        for k in order.tolist():
            key = (int(qi[k]), int(index.node_id[ti[k]]))
            wd = (int(index.way_id[ti[k]]), str(index.dir[ti[k]]))
            if seen.setdefault(key, wd) == wd:
                sel.append(k)
        sel = np.array(sorted(sel), dtype=int)
        qi, ti = qi[sel], ti[sel]
    # best class per (step, node, way, dir)
    best = {}
    for q, t in zip(qi.tolist(), ti.tolist()):
        key = (int(index.node_id[t]), int(index.way_id[t]), str(index.dir[t]))
        c = str(index.cause[t])
        if c not in rank:
            continue
        cur = best.get((q, key))
        if cur is None or rank[c] < rank[cur[0]]:
            best[(q, key)] = (c, t)
    prev_keys, cur_keys, prev_q = set(), set(), -2
    matched = set()
    for (q, key), (c, t) in sorted(best.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if q != prev_q:
            if q != prev_q + 1:
                prev_keys = set()
            else:
                prev_keys = cur_keys
            cur_keys = set()
            prev_q = q
        if key in prev_keys:  # same arrival already counted at the previous point
            cur_keys.add(key)
            continue
        cur_keys.add(key)
        p = model.p(c)
        by_class[c]["events"] += 1
        by_class[c]["expected"] += p
        res.expected_stops += p
        res.expected_stop_s += p * model.mean_stop_s(c)
        matched.add(key[0])
        res.hits.append({"lat": float(index.lat[t]), "lon": float(index.lon[t]),
                         "node_id": key[0], "cause": c, "p": p,
                         "dist_along_km": cum[q + 1] / 1000})
    res.diagnostics["matched_nodes"] = len(matched)
    if res.distance_km > 0:
        res.stops_per_km = res.expected_stops / res.distance_km
    return res
