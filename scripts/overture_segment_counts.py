"""Count Overture segments (emq.22 Overture-vs-OSM comparison; input from `uvx overturemaps download ... -f geojson`): class/subclass, km, property keys, cycle-related info, sources. Streams the GeoJSON."""
import itertools
import json
import math
import sys
from collections import Counter, defaultdict

path = sys.argv[1]

def km(coords):
    t = 0.0
    for (x1, y1), (x2, y2) in itertools.pairwise(coords):
        dx = math.radians(x2 - x1) * math.cos(math.radians((y1 + y2) / 2))
        t += 6371.0088 * math.hypot(dx, math.radians(y2 - y1))
    return t

def walk(o, pref=""):
    """yield (dotted key path, leaf value) for nested dicts/lists."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, f"{pref}.{k}" if pref else k)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v, pref + "[]")
    else:
        yield pref, o

n = Counter(); L = defaultdict(float); keys = Counter(); cyc_paths = Counter(); cyc_vals = Counter()
src = Counter(); src_by_class = defaultdict(Counter); flags = Counter(); lanes_present = Counter()
subclass_rules_vals = Counter(); road_subclass_cyc = Counter(); examples = {}
access_modes = Counter(); surface = Counter(); speed = Counter(); routes = Counter(); level_rules = 0
versions = Counter()
first = None
with open(path) as f:
    data = json.load(f)
for ft in data["features"]:
    if True:
        p = ft["properties"]; g = ft["geometry"]
        if first is None: first = ft
        st = p.get("subtype"); cl = p.get("class"); sc = p.get("subclass")
        k = km(g["coordinates"]) if g["type"] == "LineString" else 0
        n[(st, cl)] += 1; L[(st, cl)] += k
        if sc: n[(st, cl, "sub:" + str(sc))] += 1; L[(st, cl, "sub:" + str(sc))] += k
        for kp, v in walk(p):
            keys[kp] += 1
            kl = kp.lower(); vl = str(v).lower()
            if "bike" in kl or "cycle" in kl or "bicycle" in vl or "cycle" in vl or "bike" in vl:
                cyc_paths[kp] += 1; cyc_vals[(kp, str(v))] += 1
                examples.setdefault((kp, str(v)), (ft["id"], cl, sc))
        if "road_flags" in p:
            for rf in p["road_flags"]:
                for v in rf.get("values", []): flags[v] += 1
        if "lanes" in p: lanes_present[cl] += 1
        if "subclass_rules" in p:
            for r in p["subclass_rules"]: subclass_rules_vals[r.get("value")] += 1
        if "access_restrictions" in p:
            for ar in p["access_restrictions"]:
                for m in (ar.get("when") or {}).get("mode", []) or []: access_modes[(ar.get("access_type"), m)] += 1
        if "road_surface" in p:
            for s in p["road_surface"]: surface[s.get("value")] += 1
        if "speed_limits" in p: speed[cl] += 1
        if "routes" in p:
            for r in p["routes"]: routes[(r.get("network"), r.get("ref") or r.get("name"))] += 1
        if "level_rules" in p: level_rules += 1
        if "version" in p: versions[p["version"]] += 1
        for s in p.get("sources", []):
            d = s.get("dataset"); src[d] += 1; src_by_class[cl][d] += 1
            if s.get("property") in (None, ""): src[("primary", d)] += 1
        if cl == "cycleway" or sc == "cycle_crossing" or (sc or "").startswith("cycle"):
            road_subclass_cyc[(cl, sc)] += 1
def J(c): return {"|".join(str(x) for x in (k if isinstance(k, tuple) else (k,))): (round(v, 1) if isinstance(v, float) else v) for k, v in sorted(c.items(), key=lambda kv: -kv[1] if not isinstance(kv[1], tuple) else 0)}
print(json.dumps({
 "total": sum(v for k, v in n.items() if len(k) == 2),
 "counts": J(n), "km": J(L), "keys": J(keys), "cycle_paths": J(cyc_paths),
 "cycle_vals": J(cyc_vals), "cycle_examples": {"|".join(k): v for k, v in list(examples.items())[:60]},
 "road_flags": J(flags), "lanes_present_by_class": J(lanes_present), "subclass_rules_vals": J(subclass_rules_vals),
 "access_modes": J(access_modes), "surface": J(surface), "speed_limits_by_class": J(speed), "routes_top": J(Counter(dict(routes.most_common(25)))),
 "level_rules": level_rules, "sources": J(src), "sources_by_class": {str(c): J(s) for c, s in src_by_class.items()},
 "cycle_subclass": J(road_subclass_cyc), "versions": J(Counter(dict(versions.most_common(10)))),
 "first_feature_props": first["properties"] if first else None,
}, indent=1))
