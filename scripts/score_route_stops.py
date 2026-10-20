#!/usr/bin/env python3
"""Score a route (GPX) for expected stops and right turns.

Usage:
  uv run scripts/score_route_stops.py ROUTE.gpx [ROUTE2.gpx ...] \
      [--pbf data/osm/ireland.osm.pbf] [--events data/osm/events_dublin_wicklow.csv]

Method
  1. Load all `highway=*` ways (with node ids + locations) near the route from the PBF (pyosmium), project to
     EPSG:2157 (Irish Transverse Mercator) and build a shapely STRtree over their vertices.
  2. Snap each GPX trackpoint to the nearest OSM vertex (<= 5 m). BRouter writes OSM node positions, so this
     recovers the node sequence exactly; consecutive vertices are mapped to the (way, direction) edge.
  3. Stop causes: NOT re-derived. The dhy.10 classification (scripts/osm_stop_features.py: explicit
     signals/stop/give_way/mini-roundabout/signal-crossing nodes, approach-node attribution, roundabout
     entries, inferred yields, equal-class 0.5) is run once with `--causes-csv`, which logs every event as
     (way_id, dir, vertex_idx, node_id, cause, amount) = "arriving on that way in that direction at that
     vertex". The scorer sums the events hit while the route arrives at each vertex, so the rule is
     exactly dhy.10's. Regenerate the events file with:
       uv run scripts/osm_stop_features.py data/osm/ireland.osm.pbf --bbox=-6.6,52.95,-6.0,53.4 \
         --csv /tmp/s.csv --full-csv /tmp/f.csv --signals /tmp/sig.csv --causes-csv data/osm/events_dublin_wicklow.csv
  4. Right turns: at a junction node (>= 2 distinct road-class ways, dhy.10 class set) not on a roundabout,
     heading in = bearing from the route point >= 10 m before the node, heading out = bearing to the route
     point >= 10 m after; clockwise change in [+30, +150] degrees counts as a right turn (Ireland drives
     on the left, so a right turn crosses oncoming traffic). Left turns (-150..-30) counted for reference.
"""
import argparse
import csv
import math
import re
import sys
from collections import Counter, defaultdict

import gpxpy
import numpy as np
import osmium
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import Point

ROADS = {"trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "service"}
CAUSES = ["signal", "stop", "give_way", "yield_infer", "yield_equal", "rb_entry", "xing_signal"]
TR = Transformer.from_crs(4326, 2157, always_xy=True)
SNAP_M = 5.0


def load_ways(pbf, bbox):
    """highway ways with >= 1 vertex in bbox: {way_id: (hw, is_roundabout, [(node, x, y), ...])}"""
    lo_lon, lo_lat, hi_lon, hi_lat = bbox
    out = {}
    fp = (osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations()
          .with_filter(osmium.filter.KeyFilter("highway")))
    for w in fp:
        if not w.is_way():
            continue
        pts, inside = [], False
        for n in w.nodes:
            if not n.location.valid():
                continue
            lon, lat = n.lon, n.lat
            pts.append((n.ref, lon, lat))
            if lo_lon <= lon <= hi_lon and lo_lat <= lat <= hi_lat:
                inside = True
        if not inside or len(pts) < 2:
            continue
        t = w.tags
        hw = t.get("highway")
        base = hw[:-5] if (hw or "").endswith("_link") else hw
        if base in ROADS and not (hw == "service" and "service" in t):
            cls = "road"
        else:
            cls = "other"
        xs, ys = TR.transform([p[1] for p in pts], [p[2] for p in pts])
        out[w.id] = (cls, t.get("junction") in ("roundabout", "circular"),
                     [(p[0], float(x), float(y)) for p, x, y in zip(pts, xs, ys)])
    return out


def bearing(x0, y0, x1, y1):
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360


def ascent(eles, hyst=3.0):
    """Sum of climbs with a 3 m hysteresis (ignores noise smaller than hyst)."""
    if not eles:
        return 0.0
    tot, ref, lo = 0.0, eles[0], eles[0]
    for e in eles[1:]:
        if e > ref + hyst:
            tot += e - ref
            ref = e
        elif e < ref - hyst:
            ref = e
    return tot


def score(gpx_path, ways, events):
    g = gpxpy.parse(open(gpx_path))
    pts = [(p.longitude, p.latitude, p.elevation) for t in g.tracks for s in t.segments for p in s.points]
    xs, ys = TR.transform([p[0] for p in pts], [p[1] for p in pts])
    xy = list(zip(map(float, xs), map(float, ys)))
    dist = sum(math.dist(xy[i], xy[i + 1]) for i in range(len(xy) - 1))
    asc = ascent([p[2] for p in pts if p[2] is not None])
    m = re.search(r"filtered ascend = (\d+)", open(gpx_path).read(2000))
    brouter_asc = int(m.group(1)) if m else None

    # vertex STRtree + edge index
    vx, vinfo = [], []
    for wid, (cls, rb, vs) in ways.items():
        for i, (nid, x, y) in enumerate(vs):
            vx.append(Point(x, y))
            vinfo.append(nid)
    tree = STRtree(vx)
    edges = defaultdict(list)  # (nodeA, nodeB) -> [(way_id, idxB, dir)]
    node_roadways = defaultdict(set)
    node_rb = set()
    node_xy = {}
    for wid, (cls, rb, vs) in ways.items():
        for i, (nid, x, y) in enumerate(vs):
            node_xy[nid] = (x, y)
            if cls == "road":
                node_roadways[nid].add(wid)
            if rb:
                node_rb.add(nid)
            if i + 1 < len(vs):
                edges[(nid, vs[i + 1][0])].append((wid, i + 1, "fwd"))
                edges[(vs[i + 1][0], nid)].append((wid, i, "bwd"))
    seq = []
    unsnapped = 0
    for (x, y) in xy:
        j = tree.query_nearest(Point(x, y), max_distance=SNAP_M, all_matches=False)
        if len(j) == 0:
            unsnapped += 1
            continue
        nid = vinfo[int(j[0])]
        if not seq or seq[-1] != nid:
            seq.append(nid)
    # BRouter's GPX drops near-collinear points, so consecutive snapped vertices may not be adjacent: fill the
    # gap with the intermediate vertices of a way containing both (shortest span), else a local Dijkstra.
    import heapq
    pos = defaultdict(list)  # node -> [(way, idx)]
    for wid, (cls, rb, vs) in ways.items():
        for i, v in enumerate(vs):
            pos[v[0]].append((wid, i))
    adj = defaultdict(list)
    for (u, v) in edges:
        adj[u].append(v)
    filled, nfill, nfail = [seq[0]] if seq else [], 0, 0
    for a, b in zip(seq, seq[1:]):
        if (a, b) in edges:
            filled.append(b)
            continue
        best = None
        for (w1, i1) in pos[a]:
            for (w2, i2) in pos[b]:
                if w1 == w2 and (best is None or abs(i1 - i2) < abs(best[1] - best[2])):
                    best = (w1, i1, i2)
        if best:
            w1, i1, i2 = best
            vs = ways[w1][2]
            step = 1 if i2 > i1 else -1
            filled += [vs[i][0] for i in range(i1 + step, i2 + step, step)]
            nfill += 1
            continue
        # local Dijkstra (<= 600 m)
        dd, prev, pq = {a: 0.0}, {}, [(0.0, a)]
        while pq:
            du, u = heapq.heappop(pq)
            if u == b or du > 600:
                break
            if du > dd.get(u, 1e18):
                continue
            for v in adj[u]:
                nd = du + math.dist(node_xy[u], node_xy[v])
                if nd < dd.get(v, 1e18):
                    dd[v], prev[v] = nd, u
                    heapq.heappush(pq, (nd, v))
        if b in prev:
            path, u = [], b
            while u != a:
                path.append(u)
                u = prev[u]
            filled += path[::-1]
            nfill += 1
        else:
            filled.append(b)
            nfail += 1
    seq = filled
    by_cause = Counter()
    gap_m = other_m = road_m = 0.0
    arrivals = []  # (node, way_id) used for turns
    for a, b in zip(seq, seq[1:]):
        cand = edges.get((a, b))
        L = math.dist(node_xy[a], node_xy[b])
        if not cand:
            gap_m += L
            continue
        # prefer a road-class way
        cand = sorted(cand, key=lambda c: ways[c[0]][0] != "road")
        wid, ib, d = cand[0]
        if ways[wid][0] != "road":
            other_m += L
        else:
            road_m += L
        for cause, amt in events.get((wid, d, ib, b), ()):
            by_cause[cause] += amt
    # right turns
    right = left = 0
    cum = [0.0]
    for a, b in zip(seq, seq[1:]):
        cum.append(cum[-1] + math.dist(node_xy[a], node_xy[b]))
    for k in range(1, len(seq) - 1):
        n = seq[k]
        if len(node_roadways.get(n, ())) < 2 or n in node_rb:
            continue
        i0 = k - 1
        while i0 > 0 and cum[k] - cum[i0] < 10:
            i0 -= 1
        i1 = k + 1
        while i1 < len(seq) - 1 and cum[i1] - cum[k] < 10:
            i1 += 1
        x, y = node_xy[n]
        hin = bearing(*node_xy[seq[i0]], x, y)
        hout = bearing(x, y, *node_xy[seq[i1]])
        ch = (hout - hin + 180) % 360 - 180
        if 30 <= ch <= 150:
            right += 1
        elif -150 <= ch <= -30:
            left += 1
    return dict(dist=dist, asc=asc, brouter_asc=brouter_asc, causes=by_cause, right=right, left=left,
                nodes=len(seq), unsnapped=unsnapped, nfill=nfill, nfail=nfail, gap_m=gap_m, other_m=other_m, road_m=road_m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gpx", nargs="+")
    ap.add_argument("--pbf", default="data/osm/ireland.osm.pbf")
    ap.add_argument("--events", default="data/osm/events_dublin_wicklow.csv")
    a = ap.parse_args()
    events = defaultdict(list)
    with open(a.events) as f:
        for r in csv.DictReader(f):
            events[(int(r["way_id"]), r["dir"], int(r["vertex_idx"]), int(r["node_id"]))].append(
                (r["cause"], float(r["amount"])))
    # bbox of all routes, +0.02 deg
    allp = []
    for p in a.gpx:
        g = gpxpy.parse(open(p))
        allp += [(q.longitude, q.latitude) for t in g.tracks for s in t.segments for q in s.points]
    bbox = (min(q[0] for q in allp) - .02, min(q[1] for q in allp) - .02,
            max(q[0] for q in allp) + .02, max(q[1] for q in allp) + .02)
    ways = load_ways(a.pbf, bbox)
    print(f"# loaded {len(ways)} highway ways near routes", file=sys.stderr)
    hdr = ["route", "km", "stops", "stops/km"] + [f"{c}/km" for c in CAUSES] + ["right", "left", "ascent_m",
                                                                                 "brouter_asc", "unmatched_km"]
    print("| " + " | ".join(hdr) + " |\n|" + "---|" * len(hdr))
    for p in a.gpx:
        r = score(p, ways, events)
        km = r["dist"] / 1000
        tot = sum(r["causes"].values())
        row = [p.split("/")[-1], f"{km:.2f}", f"{tot:.1f}", f"{tot/km:.2f}"]
        row += [f"{r['causes'].get(c, 0)/km:.2f}" for c in CAUSES]
        row += [str(r["right"]), str(r["left"]), f"{r['asc']:.0f}", str(r["brouter_asc"]),
                f"{(r['gap_m'] + r['other_m'])/1000:.2f}"]
        print("| " + " | ".join(row) + " |")
        print(f"#   {p}: nodes={r['nodes']} unsnapped_pts={r['unsnapped']} gap_km={r['gap_m']/1000:.2f} "
              f"gaps_filled={r['nfill']} gaps_unfilled={r['nfail']} non-road-class_km={r['other_m']/1000:.2f} road_km={r['road_m']/1000:.2f}", file=sys.stderr)


if __name__ == "__main__":
    main()
