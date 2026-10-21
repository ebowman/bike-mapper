"""Build the cycle-infrastructure overlay GeoJSON for the planner map (web/data/cycle_dublin_wicklow.geojson).

One pass over the OSM PBF. Emits:
  kind=path  highway=cycleway ways
  kind=lane  road ways with a cycleway* tag value in LANE_VALUES
  kind=track road ways with a cycleway* tag value in TRACK_VALUES (track wins over lane if both are present)
Cycle route relations are out of scope. Counts and km per kind go to stderr.

  uv run scripts/build_cycle_overlay.py [--pbf data/osm/ireland.osm.pbf] [--bbox -6.6,52.95,-6.0,53.4]
"""
import argparse
import itertools
import json
import math
import sys
from pathlib import Path

import osmium
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parent.parent
ROAD_HW = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary",
           "secondary_link", "tertiary", "tertiary_link", "unclassified", "residential", "living_street", "service"}
CYCLEWAY_KEYS = ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both")
LANE_VALUES = {"lane", "shared_lane", "share_busway", "opposite_lane"}
TRACK_VALUES = {"track", "opposite_track", "separate"}
PATH_TAGS = ("surface", "segregated", "foot", "oneway", "name")
ROAD_TAGS = CYCLEWAY_KEYS + ("highway", "maxspeed", "name")


def classify(tags):
    """Return (kind, side) for a road's tags: kind in lane/track/None, side in left/right/both/None.

    Track beats lane when both occur. Side comes from the key of the winning value:
    cycleway:left -> left, cycleway:right -> right, cycleway:both -> both, plain cycleway -> both.
    If the winning kind is present on both left and right it is 'both'.
    """
    found = {}  # kind -> set of sides
    for key in CYCLEWAY_KEYS:
        v = tags.get(key)
        kind = "lane" if v in LANE_VALUES else "track" if v in TRACK_VALUES else None
        if kind:
            side = {"cycleway:left": "left", "cycleway:right": "right"}.get(key, "both")
            found.setdefault(kind, set()).add(side)
    if not found:
        return None, None
    kind = "track" if "track" in found else "lane"
    sides = found[kind]
    side = "both" if ("both" in sides or sides == {"left", "right"}) else next(iter(sides))
    return kind, side


def km(coords):
    t = 0.0
    for (x1, y1), (x2, y2) in itertools.pairwise(coords):
        dx = math.radians(x2 - x1) * math.cos(math.radians((y1 + y2) / 2))
        t += 6371.0088 * math.hypot(dx, math.radians(y2 - y1))
    return t


class Overlay(osmium.SimpleHandler):
    def __init__(self, bbox):
        super().__init__()
        self.bbox = bbox
        self.feats = []

    def way(self, w):
        hw = w.tags.get("highway")
        if hw is None or len(w.nodes) < 2:
            return
        if hw == "cycleway":
            kind, side, keys = "path", None, PATH_TAGS
        elif hw in ROAD_HW:
            kind, side = classify(w.tags)
            if kind is None:
                return
            keys = ROAD_TAGS
        else:
            return
        try:
            pts = [(n.lon, n.lat) for n in w.nodes]
        except Exception:  # noqa: BLE001 - ways with missing node locations are skipped
            return
        x0, y0, x1, y1 = self.bbox
        if not any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in pts):
            return
        g = [(round(x, 5), round(y, 5)) for x, y in LineString(pts).simplify(1.5e-5).coords]
        if len(g) < 2:
            return
        props = {"kind": kind, "way": w.id}
        if side:
            props["side"] = side
        for k in keys:
            if k in w.tags:
                props[k] = w.tags[k]
        self.feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": g}, "properties": props})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pbf", default=str(ROOT / "data" / "osm" / "ireland.osm.pbf"))
    ap.add_argument("--bbox", default="-6.6,52.95,-6.0,53.4", help="minlon,minlat,maxlon,maxlat")
    ap.add_argument("--out", default=str(ROOT / "web" / "data" / "cycle_dublin_wicklow.geojson"))
    a = ap.parse_args()
    bbox = tuple(float(v) for v in a.bbox.split(","))
    if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        sys.exit("--bbox must be minlon,minlat,maxlon,maxlat")
    h = Overlay(bbox)
    h.apply_file(a.pbf, locations=True)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "features": h.feats}, separators=(",", ":")))
    for kind in ("path", "lane", "track"):
        fs = [f for f in h.feats if f["properties"]["kind"] == kind]
        d = sum(km(f["geometry"]["coordinates"]) for f in fs)
        print(f"{kind}: {len(fs)} features, {d:.1f} km", file=sys.stderr)
    print(f"{out}: {out.stat().st_size/1e6:.2f} MB", file=sys.stderr)


if __name__ == "__main__":
    main()
