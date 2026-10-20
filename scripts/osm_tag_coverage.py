#!/usr/bin/env python3
"""OSM tag coverage by highway class (length-weighted, geodesic via haversine).

Usage: uv run scripts/osm_tag_coverage.py <file.osm.pbf>

Prints markdown tables: (1) tag coverage per class, (2) surface top-10 and
smoothness values on tertiary+unclassified, (3) restriction counts
(bicycle=no, access=no, access=private) by class.
Relations are ignored (tags inherited from route/cycle-network relations
are not counted).
"""
import math
import sys
import time
from collections import Counter, defaultdict

import osmium

CLASSES = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
           "residential", "living_street", "cycleway", "track", "path", "service"]
CLS = set(CLASSES)
TAGS = ["surface", "smoothness", "maxspeed", "lanes", "width", "lit",
        "cycleway*", "bicycle", "traffic_calming", "oneway", "name"]
R = 6371008.8


def hav(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


class H(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.km = Counter()
        self.ways = Counter()
        self.tagkm = defaultdict(Counter)
        self.surf = Counter()
        self.smooth = Counter()
        self.restr = defaultdict(Counter)

    def way(self, w):
        t = w.tags
        hw = t.get("highway")
        if hw not in CLS:
            return
        pts = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
        L = sum(hav(*pts[i], *pts[i + 1]) for i in range(len(pts) - 1)) / 1000.0
        self.km[hw] += L
        self.ways[hw] += 1
        keys = {tg.k: tg.v for tg in t}
        for tag in TAGS:
            if tag == "cycleway*":
                present = any(k.startswith("cycleway") for k in keys)
            else:
                present = tag in keys
            if present:
                self.tagkm[hw][tag] += L
        if hw in ("tertiary", "unclassified"):
            self.surf[keys.get("surface", "(missing)")] += L
            self.smooth[keys.get("smoothness", "(missing)")] += L
        if keys.get("bicycle") == "no":
            self.restr[hw]["bicycle=no"] += 1
        if keys.get("access") == "no":
            self.restr[hw]["access=no"] += 1
        if keys.get("access") == "private":
            self.restr[hw]["access=private"] += 1


def main():
    t0 = time.time()
    h = H()
    h.apply_file(sys.argv[1], locations=True)
    print(f"<!-- {sys.argv[1]} processed in {time.time()-t0:.0f}s -->\n")
    print("### Tag coverage (% of length) by highway class\n")
    print("| class | ways | km | " + " | ".join(TAGS) + " |")
    print("|---|---|---|" + "---|" * len(TAGS))
    tot = Counter()
    for c in CLASSES:
        if not h.km[c]:
            continue
        print(f"| {c} | {h.ways[c]} | {h.km[c]:.0f} | " +
              " | ".join(f"{100*h.tagkm[c][t]/h.km[c]:.1f}" for t in TAGS) + " |")
    tk = sum(h.km.values())
    print(f"| ALL | {sum(h.ways.values())} | {tk:.0f} | " +
          " | ".join(f"{100*sum(h.tagkm[c][t] for c in CLASSES)/tk:.1f}" for t in TAGS) + " |")
    tu = h.km["tertiary"] + h.km["unclassified"]
    print(f"\n### Surface on tertiary+unclassified (top 10, {tu:.0f} km)\n")
    print("| surface | km | % |\n|---|---|---|")
    for v, k in h.surf.most_common(10):
        print(f"| {v} | {k:.0f} | {100*k/tu:.1f} |")
    print("\n### Smoothness on tertiary+unclassified (all values)\n")
    print("| smoothness | km | % |\n|---|---|---|")
    for v, k in h.smooth.most_common():
        print(f"| {v} | {k:.1f} | {100*k/tu:.2f} |")
    print("\n### Restricted ways (count) by class\n")
    print("| class | bicycle=no | access=no | access=private |\n|---|---|---|---|")
    for c in CLASSES:
        r = h.restr[c]
        print(f"| {c} | {r['bicycle=no']} | {r['access=no']} | {r['access=private']} |")


if __name__ == "__main__":
    main()
