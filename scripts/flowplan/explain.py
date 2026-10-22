"""Per-route debug explanation built from BRouter message segments (Candidate.segments)."""
from __future__ import annotations

from .brouter import CYCLEWAY_KEYS, cycle_km
from .scoring import haversine_m

HIT_SNAP_M = 30.0


def cycleway_string(tags: dict) -> str | None:
    """Collapse cycleway / cycleway:left|right|both into one string, or None if untagged."""
    found = [(k.partition(":")[2] or "", tags[k]) for k in CYCLEWAY_KEYS if tags.get(k)]
    if not found:
        return None
    vals = {v for _, v in found}
    if len(vals) == 1:
        return found[0][1]
    return ", ".join(f"{s}={v}" if s else v for s, v in found)


def highway_class(tags: dict) -> str:
    return tags.get("highway") or ("ferry" if tags.get("route") == "ferry" else "unknown")


def assign_hits(segments: list, hits: list, snap_m: float = HIT_SNAP_M) -> list:
    """For each hit return the index of the segment whose END point is nearest the hit's
    (lat, lon): nearest within snap_m, else simply the nearest (-1 when there are no segments).
    scoring's dist_along_km is the distance to the end of the matched route step, not a range
    into BRouter's segments, so positions are compared instead."""
    out = []
    for h in hits:
        best, best_d = -1, float("inf")
        for i, sg in enumerate(segments):
            d = haversine_m(h["lon"], h["lat"], sg["lon"], sg["lat"])
            if d < best_d:
                best, best_d = i, d
        out.append(best)
    return out


def explain(segments: list, hits: list, total_cost: float = 0.0) -> dict:
    """-> {"segments": [...], "summary": {...}}."""
    owner = assign_hits(segments, hits)
    per = [[] for _ in segments]
    for h, i in zip(hits, owner, strict=True):
        if i >= 0:
            per[i].append({"cause": h["cause"], "p": h["p"]})
    rows, by_class, cum, charges = [], {}, 0.0, 0
    for i, sg in enumerate(segments):
        tags = sg.get("way_tags") or {}
        d = float(sg.get("dist_m", 0) or 0)
        hw = highway_class(tags)
        by_class[hw] = by_class.get(hw, 0.0) + d / 1000
        nc, ic, tc = (float(sg.get(k, 0) or 0) for k in ("node_cost", "initial_cost", "turn_cost"))
        if nc + ic > 0:
            charges += 1
        rows.append({"i": i, "lon": sg.get("lon"), "lat": sg.get("lat"), "start_km": cum / 1000, "end_km": (cum + d) / 1000, "dist_m": d,
                     "highway": hw, "cycleway": cycleway_string(tags),
                     "surface": tags.get("surface"), "maxspeed": tags.get("maxspeed"),
                     "name": tags.get("name"), "cost_per_km": float(sg.get("cost_per_km", 0) or 0),
                     "node_cost": nc, "initial_cost": ic, "turn_cost": tc, "hits": per[i]})
        cum += d
    return {"segments": rows,
            "summary": {"km_by_highway": by_class, "cycle_km": cycle_km(segments),
                        "n_node_charges": charges, "total_brouter_cost": total_cost}}


# ---- rideability warnings (41w.13): server-side guard in case the BRouter profile misses an unrideable way ----
BAD_SMOOTHNESS = ("impassable", "very_horrible", "horrible")
OFFROAD_HIGHWAYS = ("path", "footway")
BIKE_OK = ("yes", "designated")


def ride_warnings(segments: list) -> list[str]:
    """Human-readable warnings for a route whose segments include ways a road bike should not use: bicycle=no,
    smoothness impassable/very_horrible/horrible, or highway=path|footway without bicycle=yes|designated.
    One line per kind with the km affected; [] when the route is clean."""
    km = {"bicycle=no": 0.0, "smoothness": 0.0, "path": 0.0}
    for sg in segments:
        t = sg.get("way_tags") or {}
        d = float(sg.get("dist_m", 0) or 0) / 1000
        if t.get("bicycle") == "no":
            km["bicycle=no"] += d
        if t.get("smoothness") in BAD_SMOOTHNESS:
            km["smoothness"] += d
        if t.get("highway") in OFFROAD_HIGHWAYS and t.get("bicycle") not in BIKE_OK:
            km["path"] += d
    msgs = {"bicycle=no": "{:.1f} km on ways tagged bicycle=no",
            "smoothness": "{:.1f} km on ways with smoothness impassable/very_horrible/horrible",
            "path": "{:.1f} km on highway=path/footway without bicycle=yes|designated"}
    return ["routes over unrideable ways: " + msgs[k].format(v) for k, v in km.items() if v > 0]
