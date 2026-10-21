"""Count OSM cycle infrastructure in a bbox (emq.22 Overture-vs-OSM comparison): highway=cycleway ways, roads with cycleway* lane/track tags
(build_cycle_overlay.classify), plus highway class totals, by count and km (clipped to bbox by vertex)."""
import itertools
import json
import math
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import osmium
from build_cycle_overlay import CYCLEWAY_KEYS, ROAD_HW, classify

pbf = sys.argv[1]
x0, y0, x1, y1 = (float(v) for v in sys.argv[2].split(","))

def seglen(a, b):
    dx = math.radians(b[0]-a[0]) * math.cos(math.radians((a[1]+b[1])/2))
    return 6371.0088 * math.hypot(dx, math.radians(b[1]-a[1]))

def inb(p):
    return x0 <= p[0] <= x1 and y0 <= p[1] <= y1

class H(osmium.SimpleHandler):
    def __init__(s):
        super().__init__()
        s.n = Counter(); s.km = defaultdict(float)
        s.cwvals = Counter(); s.keys = Counter()
    def way(s, w):
        hw = w.tags.get("highway")
        if hw is None or len(w.nodes) < 2: return
        try: pts = [(n.lon, n.lat) for n in w.nodes]
        except Exception:  # noqa: BLE001 - ways with missing node locations are skipped
            return
        # km inside bbox: sum segments with both endpoints inside
        k = sum(seglen(a, b) for a, b in itertools.pairwise(pts) if inb(a) and inb(b))
        if not any(inb(p) for p in pts): return
        def add(cat):
            s.n[cat] += 1; s.km[cat] += k
        add(("hw", hw))
        if hw == "cycleway":
            add(("cycle", "path"))
            if w.tags.get("segregated") == "yes": add(("cycle", "path_segregated"))
            if w.tags.get("foot") in ("yes","designated"): add(("cycle", "path_shared_foot"))
        elif hw in ROAD_HW:
            kind, _side = classify(w.tags)
            if kind:
                add(("cycle", kind)); add(("cycle_hw", hw, kind))
            anycw = any(key in w.tags for key in CYCLEWAY_KEYS)
            if anycw:
                add(("cycle", "any_cycleway_key"))
                for key in CYCLEWAY_KEYS:
                    if key in w.tags: s.cwvals[w.tags[key]] += 1
            if w.tags.get("bicycle") == "designated": add(("cycle", "road_bicycle_designated"))
        if hw in ("path","footway"):
            if w.tags.get("bicycle") in ("yes","designated"): add(("cycle", f"{hw}_bicycle_yes"))
            if w.tags.get("bicycle") == "designated": add(("cycle", f"{hw}_bicycle_designated"))
        for key, val in w.tags:
            if "cycle" in key or "bike" in key: s.keys[key] += 1
        if hw in ROAD_HW or hw == "cycleway":
            for t in ("surface","smoothness","maxspeed","lanes","lit","width"):
                if t in w.tags: add(("tag", "road" if hw in ROAD_HW else "cycleway", t))
            add(("tag", "road" if hw in ROAD_HW else "cycleway", "_all"))

h = H(); h.apply_file(pbf, locations=True)
out = {"counts": {"|".join(k): v for k, v in h.n.items()}, "km": {"|".join(k): round(v, 1) for k, v in h.km.items()},
       "cycleway_values": dict(h.cwvals.most_common()), "cycle_keys": dict(h.keys.most_common(40))}
print(json.dumps(out, indent=1))
