"""Build small GeoJSON files for docs/map/index.html from data/samples/ CSVs/GPX and the OSM PBFs."""
import csv, json, sys
from pathlib import Path
import gpxpy, osmium
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parent.parent
S = ROOT / "data" / "samples"
OUT = ROOT / "docs" / "map" / "data"
CACHE = ROOT / "data" / "osm"
MAX_BYTES = 2_000_000
REGIONS = {
    "ireland": dict(ways="stops_per_km_wicklow.csv", pbf="ireland.osm.pbf"),
    "berlin": dict(ways="stops_per_km_berlin.csv", pbf="brandenburg.osm.pbf"),
}
KEEP_HW = {"tertiary", "unclassified", "secondary", "primary", "residential"}


def r5(x):
    return round(float(x), 5)


def num(v):
    return None if v in ("", None) else float(v)


def write(name, feats):
    p = OUT / name
    p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    size = p.stat().st_size
    print(f"{name}: {len(feats)} features, {size/1e6:.2f} MB")
    return size


class Geoms(osmium.SimpleHandler):
    def __init__(self, ids):
        super().__init__()
        self.ids, self.geoms = ids, {}

    def way(self, w):
        if w.id in self.ids:
            try:
                self.geoms[w.id] = [(r5(n.lon), r5(n.lat)) for n in w.nodes]
            except Exception:
                pass


def way_geoms(region, ids):
    cache = CACHE / f"map_way_geoms_{region}.json"
    if cache.exists():
        d = json.loads(cache.read_text())
        if set(map(int, d)) >= ids:
            return {int(k): v for k, v in d.items()}
    h = Geoms(ids)
    h.apply_file(str(CACHE / REGIONS[region]["pbf"]), locations=True)
    cache.write_text(json.dumps(h.geoms))
    return h.geoms


def build_ways(region):
    rows = list(csv.DictReader(open(S / REGIONS[region]["ways"])))
    rows = [r for r in rows if float(r["length_km"]) >= 0.05]
    geoms = way_geoms(region, {int(r["way_id"]) for r in rows})

    def feats(rs):
        out = []
        for r in rs:
            g = geoms.get(int(r["way_id"]))
            vals = [v for v in (num(r["stops_per_km_fwd"]), num(r["stops_per_km_bwd"])) if v is not None]
            if not g or len(g) < 2 or not vals:
                continue
            # Douglas-Peucker at ~1.5 m keeps shapes but shrinks files
            g = [(r5(x), r5(y)) for x, y in LineString(g).simplify(1.5e-5).coords]
            out.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": g},
                        "properties": {"name": r["name"], "highway": r["highway"],
                                       "km": round(float(r["length_km"]), 2),
                                       "spk": round(sum(vals) / len(vals), 2)}})
        return out

    f = feats(rows)
    if len(json.dumps(f, separators=(",", ":"))) > MAX_BYTES:
        rows = [r for r in rows if r["highway"] in KEEP_HW and float(r["length_km"]) >= 0.1]
        print(f"ways_{region}: >2 MB, filtered to {sorted(KEEP_HW)} and length>=0.1 km")
        f = feats(rows)
    return f


def build_stops(region):
    out = []
    for r in csv.DictReader(open(S / f"stop_units_{region}.csv")):
        out.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r5(r["lon"]), r5(r["lat"])]},
                    "properties": {"passes": int(r["passes"]), "stops": int(r["stops"]), "p": round(float(r["p"]), 3),
                                   "cls": r["class"], "n_nodes": int(r["n_nodes"]),
                                   "diam": round(float(r["diameter_m"]), 1)}})
    return out


def build_unexplained(region):
    out = []
    for r in csv.DictReader(open(S / f"stop_model_unexplained_{region}.csv")):
        out.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r5(r["lon"]), r5(r["lat"])]},
                    "properties": {"cls": r["cls"], "n_nodes": int(r["n_nodes"]), "passes": int(r["passes"]),
                                   "stops": int(r["stops"]), "mean_stop_s": num(r["mean_stop_s"]),
                                   "ways": r["nearby_ways"], "label": r["label"], "rationale": r["rationale"]}})
    return out


def build_routes():
    out = []
    for pair in ("wicklow", "dublin"):
        for prof in ("baseline", "flow"):
            g = gpxpy.parse(open(S / f"brouter-{pair}-{prof}.gpx"))
            coords = [[r5(p.longitude), r5(p.latitude)] for t in g.tracks for s in t.segments for p in s.points]
            out.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                        "properties": {"pair": pair, "profile": prof,
                                       "km": round(sum(s.length_2d() for t in g.tracks for s in t.segments) / 1000, 1)}})
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = []
    for region in REGIONS:
        sizes.append(write(f"stops_{region}.geojson", build_stops(region)))
        sizes.append(write(f"ways_{region}.geojson", build_ways(region)))
        sizes.append(write(f"unexplained_{region}.geojson", build_unexplained(region)))
    sizes.append(write("routes.geojson", build_routes()))
    if max(sizes) > MAX_BYTES:
        sys.exit("a GeoJSON exceeds 2 MB")
    print(f"total {sum(sizes)/1e6:.2f} MB")


if __name__ == "__main__":
    main()
