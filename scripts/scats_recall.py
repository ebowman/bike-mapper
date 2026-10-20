#!/usr/bin/env python3
"""Recall of OSM traffic signals against Dublin City Council signal-site list.

Usage: uv run scripts/scats_recall.py data/traffic/sites_2025.geojson data/osm/signals_ireland.csv [radius_m=30]

DCC file: WGS84 points (CC-BY 4.0). OSM signals come from osm_stop_features.py
(--signals CSV). Both are projected to EPSG:2157 (ITM) and matched with a shapely STRtree.
"""
import csv
import json
import sys
from collections import Counter

import numpy as np
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import Point

gj, osm = sys.argv[1], sys.argv[2]
R = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
tr = Transformer.from_crs(4326, 2157, always_xy=True)
with open(gj) as fh:
    feats = json.load(fh)["features"]
sites = [(f["properties"].get("Type") or f["properties"].get("Site_Type") or "?",
          *tr.transform(*f["geometry"]["coordinates"][:2])) for f in feats if f["geometry"]]
with open(osm) as fh:
    rows = list(csv.DictReader(fh))


def recall(kinds, road_only, radius=R):
    pts = [r for r in rows if r["kind"] in kinds and (not road_only or r["on_road_way"] == "1")]
    xs = tr.transform([float(r["lon"]) for r in pts], [float(r["lat"]) for r in pts])
    tree = STRtree([Point(x, y) for x, y in zip(*xs)])
    hit, dists = Counter(), []
    tot = Counter()
    for t, x, y in sites:
        tot[t] += 1
        j = tree.query_nearest(Point(x, y), return_distance=True)
        d = float(j[1][0]) if len(j[1]) else 1e9
        dists.append(d)
        if d <= radius:
            hit[t] += 1
    return tot, hit, np.array(dists), len(pts)


print(f"DCC sites: {len(sites)}\n")
print("| OSM set | OSM nodes | radius m | sites | matched | recall % | median nearest m |\n|---|---|---|---|---|---|---|")
for label, kinds, ro in [("highway=traffic_signals (all)", {"signals"}, False),
                         ("highway=traffic_signals (on road ways)", {"signals"}, True),
                         ("signals + crossing=traffic_signals", {"signals", "xing_signals"}, False)]:
    for rad in (30, 50, 100):
        tot, hit, d, n = recall(kinds, ro, rad)
        print(f"| {label} | {n} | {rad} | {sum(tot.values())} | {sum(hit.values())} | "
              f"{100*sum(hit.values())/sum(tot.values()):.1f} | {np.median(d):.0f} |")
print("\nBy DCC site Type (signals + crossing=traffic_signals, 30 m):\n")
tot, hit, d, n = recall({"signals", "xing_signals"}, False, 30)
print("| DCC type | sites | matched | recall % |\n|---|---|---|---|")
for t, c in tot.most_common():
    print(f"| {t} | {c} | {hit[t]} | {100*hit[t]/c:.1f} |")
tot, hit, d, n = recall({"signals"}, False, 30)
print("\nBy DCC site Type (highway=traffic_signals only, 30 m):\n")
print("| DCC type | sites | matched | recall % |\n|---|---|---|---|")
for t, c in tot.most_common():
    print(f"| {t} | {c} | {hit[t]} | {100*hit[t]/c:.1f} |")
