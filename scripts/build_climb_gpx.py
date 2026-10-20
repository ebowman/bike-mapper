"""Build a climb GPX by stitching OSM way geometry (Overpass `out geom` JSON).

Usage: build_climb_gpx.py --json r756.json --start-way ID --ways ID,ID,... --out x.gpx --name NAME
Ways are given in travel order; each is reversed if needed so it joins the previous one.
Fetch JSON (Wicklow Gap, R756):
  curl -A 'bike-mapper-research/0.1' --data-urlencode \
   'data=[out:json];way["ref"="R756"](52.98,-6.45,53.06,-6.25);out geom;' \
   https://overpass-api.de/api/interpreter -o r756.json
"""
import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--ways", required=True, help="comma-separated way ids in travel order")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="climb")
    a = ap.parse_args()
    with open(a.json) as jf:
        els = {e["id"]: [(p["lat"], p["lon"]) for p in e["geometry"]] for e in json.load(jf)["elements"]}
    pts = []
    for tok in a.ways.split(","):
        wid = abs(int(tok))
        g = els[wid]
        if not pts and tok.startswith("-"):
            g = g[::-1]  # first way: leading '-' reverses it
        if pts:
            if abs(g[0][0]-pts[-1][0]) + abs(g[0][1]-pts[-1][1]) > 1e-7:
                g = g[::-1]
            if abs(g[0][0]-pts[-1][0]) + abs(g[0][1]-pts[-1][1]) > 1e-7:
                sys.exit(f"way {wid} does not join previous end {pts[-1]}")
            g = g[1:]
        pts += g
    with open(a.out, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="bike-mapper scripts/build_climb_gpx.py (OSM way geometry, ODbL)" xmlns="http://www.topografix.com/GPX/1/1">\n')
        f.write(f"<trk><name>{a.name}</name><trkseg>\n")
        f.writelines(f'<trkpt lat="{la:.7f}" lon="{lo:.7f}"/>\n' for la, lo in pts)
        f.write("</trkseg></trk></gpx>\n")
    print(f"{len(pts)} points -> {a.out}")

if __name__ == "__main__":
    main()
