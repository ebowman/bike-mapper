#!/usr/bin/env python3
"""Count mountain_pass=yes and natural=saddle nodes (and how many are named / carry ele) in OSM PBFs.

Usage: uv run python scripts/osm_passes.py data/osm/ireland.osm.pbf data/osm/baleares.osm.pbf
Only nodes are counted (the bead scope); ways/relations with these tags are ignored.
"""
import sys

import osmium


def count(path):
    c = {"mountain_pass=yes": [0, 0, 0], "natural=saddle": [0, 0, 0], "natural=peak": [0, 0, 0]}
    for o in osmium.FileProcessor(path, osmium.osm.NODE).with_filter(osmium.filter.KeyFilter("mountain_pass", "natural")):
        t = o.tags
        keys = []
        if t.get("mountain_pass") == "yes": keys.append("mountain_pass=yes")
        if t.get("natural") == "saddle": keys.append("natural=saddle")
        if t.get("natural") == "peak": keys.append("natural=peak")
        for k in keys:
            c[k][0] += 1
            if t.get("name"): c[k][1] += 1
            if t.get("ele"): c[k][2] += 1
    return c

def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print("| extract | tag | nodes | with name | with ele |\n|---|---|---:|---:|---:|")
    for p in sys.argv[1:]:
        for k, (n, nm, el) in count(p).items():
            print(f"| {p.split('/')[-1]} | {k} | {n} | {nm} | {el} |")

if __name__ == "__main__":
    main()
