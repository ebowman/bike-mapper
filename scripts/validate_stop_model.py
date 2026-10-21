#!/usr/bin/env python3
"""Validate the OSM stop-cause model (dhy.10) against Eric's observed stops (dhy.6/dhy.15).

Usage:
  uv run scripts/validate_stop_model.py     # ~6 min first run (event-node coordinate + evidence PBF passes);
                                            # ~1 min when the caches in data/osm/ exist and --no-evidence

Method (see docs/research/stop-model-validation.md):
  * UNITS: observed nodes of a region are clustered in a projected CRS. Headline = bounded-diameter
    "leader" clustering, r = 25 m (seeds in descending passes order; unit diameter <= 50 m). Sensitivity:
    leader r = 20 / 30 m and single-linkage 20 m (the upper bound; chains up to ~560 m). unit passes =
    max member passes (ride passes are NOT recounted from the tracks); unit stops = sum of member stops
    capped at unit passes (one stop per ride per unit); mean stop s = stop-weighted.
  * CLASS: each unit gets ONE class from the OSM stop-cause events (data/osm/events_*.csv; node
    coordinates from the PBF) lying within --event-m (20 m) of ANY member node, either travel
    direction, first match wins: signal > stop > give_way > rb_entry > level_crossing (PBF
    railway=level_crossing) > xing_signal > yield_infer > yield_equal > midway (nothing within 20 m).
  * Wilson 95 % intervals (implemented directly), explained fraction, precision/recall, relative
    weights (signals = 300, net of the mid-way background), top-15 unexplained units per region with
    OSM evidence within 40 m and a manual label.
"""
import argparse
import math
import pathlib
import sys
import time

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLASSES = ["signal", "stop", "give_way", "rb_entry", "level_crossing", "xing_signal",
           "yield_infer", "yield_equal", "midway"]
CAUSE_CLASSES = CLASSES[:7]  # an OSM stop-cause is present
CLASS_LABEL = {"signal": "traffic_signals", "stop": "stop sign", "give_way": "give_way sign",
               "rb_entry": "roundabout entry", "level_crossing": "level crossing",
               "xing_signal": "signalled crossing", "yield_infer": "inferred yield (minor meets major)",
               "yield_equal": "equal-class uncontrolled", "midway": "mid-way (no event)"}
REGIONS = {
    "ireland": {"obs": "data/samples/observed_stops_eric.csv", "events": "data/osm/events_ireland.csv",
                "pbf": "data/osm/ireland.osm.pbf", "crs": "EPSG:2157",
                "note": "auto-pause OFF: stops are slow-speed runs"},
    "berlin": {"obs": "data/samples/observed_stops_eric_berlin.csv", "events": "data/osm/events_berlin.csv",
               "pbf": "data/osm/brandenburg.osm.pbf", "crs": "EPSG:25833",
               "note": "auto-pause ON: stops are mostly timer gaps; nodes with <2 passes dropped upstream"},
}

# Manual labels for the top-15 unexplained units per region, from the OSM evidence + stop duration
# printed by this script (key = representative node id = member node with most passes).
# Filled in after inspecting the evidence columns of data/samples/stop_model_unexplained_*.csv.
# Label set = the bead's five + start/end proximity + other, plus the added category MODEL_GAP.
MODEL_GAP = "model gap: OSM feature present nearby but not attached"  # added to the bead's label set
CAFE = "café/photo/regroup"
MISSING = "missing OSM tag"
LABELS = {
    # --- Ireland (auto-pause off, slow-speed stops)
    ("ireland", 658732): (CAFE, "Carrickbrack Rd, no junction tags, 100 s: scenic stop"),
    ("ireland", 253242243): (MISSING, "Greys Lane residential junction, only inferred equal-class, 16 s, no sign"),
    ("ireland", 659995687): (MODEL_GAP, "traffic_calming=hump on the node + bollard 8 m (not a modelled cause), 63 s"),
    ("ireland", 4136049853): (CAFE, "Hutchinsons Strand seafront, gate + slipway, 102 s"),
    ("ireland", 187666504): ("other", "unclassified road meeting a path, nothing tagged within 40 m, 36 s"),
    ("ireland", 1727098423): (CAFE, "Carrickbrack Rd informal crossing + stile to Bog of Frogs Loop, 69 s"),
    ("ireland", 3009484963): (MODEL_GAP, "bus stop + stop_position 15 m, gate, service accesses, 25 s (bus stops are not modelled)"),
    ("ireland", 662369070): ("traffic queue", "Howth Abbey St pedestrians/shops, 7 s, no junction tags"),
    ("ireland", 686825610): (CAFE, "Howth Harbour Rd benches/bins/milestone, 33 s"),
    ("ireland", 219167289): (CAFE, "Howth Summit car park: benches, bins, tourism=viewpoint 28 m, 87 s"),
    ("ireland", 6725253387): (MODEL_GAP, "Sutton Strand bus stop_position on the node, 16 s"),
    ("ireland", 219167494): (CAFE, "Howth Summit: bicycle parking, benches, viewpoint, 63 s"),
    ("ireland", 3647682703): ("traffic queue", "Strand Rd, parking/parking_space 5-10 m, 7 s: parking manoeuvres"),
    ("ireland", 5630463604): (MISSING, "Balkill Rd/Windgate Rd residential junction, 10 s, no tags"),
    ("ireland", 302333152): (CAFE, "Strand Rd promenade bench 12 m, unmarked crossing 14 m, 73 s"),
    # --- Berlin (auto-pause on, timer gaps)
    ("berlin", 247327311): ("traffic queue", "Pfaueninselchaussee ferry access: tourism=information, bins, 10 s"),
    ("berlin", 21487185): (MODEL_GAP, "Rochstr: two unmarked crossings 6-7 m + bollards (pedestrian crossings are not modelled), 10 s"),
    ("berlin", 413278860): (CAFE, "Havelchaussee tourism=information 32 m, 73 s: viewpoint"),
    ("berlin", 8026011923): (CAFE, "Havelchaussee tourism=information 14 m, 38 s: viewpoint"),
    ("berlin", 3413071801): (CAFE, "Grosser Stern (Siegessaeule) bench/street lamps, 57 s: landmark stop"),
    ("berlin", 8995300528): (CAFE, "Str. des 17. Juni tourism=information 18 m, 105 s"),
    ("berlin", 13311134869): ("other", "Unter den Linden tram stop 8 m, bins; 13 s, cause unclear"),
    ("berlin", 12645611885): (MISSING, "path meeting tertiary Am Postfenn, 8 s, nothing tagged"),
    ("berlin", 30133333): (CAFE, "Nikolskoer Weg gate 18 m, 135 s: Nikolskoe viewpoint"),
    ("berlin", 4160071854): ("other", "Grabbeallee service access onto primary, only street lamps within 25 m, 30 s"),
    ("berlin", 10617298999): ("other", "Kollwitzstr service/residential, bicycle parking 11 m, 25 s"),
    ("berlin", 11414645634): (MODEL_GAP, "traffic_signals 22 m + signalled crossing 24 m, beyond the 20 m reach of this unit, 39 s"),
    ("berlin", 10617306940): ("data noise", "4 s, close to detection floor; bicycle parking only"),
    ("berlin", 7710514833): (MODEL_GAP, "railway=tram_level_crossing 1 m (only railway=level_crossing is modelled), 26 s"),
    ("berlin", 2260518688): (MODEL_GAP, "bus stop 17 m + stop_position 19 m, platform Schaeferberg, 47 s"),
}


def wilson(k, n, z=1.96):
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / d), min(1.0, (c + h) / d))


# ----------------------------------------------------------------------------- units
def level_crossing_points(pbf):
    import osmium
    out = []
    fp = osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(osmium.filter.KeyFilter("railway"))
    for n in fp:
        if n.tags.get("railway") == "level_crossing" and n.location.valid():
            out.append((n.id, n.location.lon, n.location.lat))
    return out


def node_coords(pbf, ids, cache):
    """lon/lat of the given node ids (pyosmium IdFilter pass, cached as csv)."""
    import osmium
    if cache.exists():
        c = pd.read_csv(cache)
        if set(ids) <= set(c.node_id):
            return c
    t = time.time()
    rows = [(n.id, n.location.lon, n.location.lat)
            for n in osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(osmium.filter.IdFilter(list(ids)))
            if n.location.valid()]
    c = pd.DataFrame(rows, columns=["node_id", "lon", "lat"])
    c.to_csv(cache, index=False)
    print(f"  event-node coordinates: {len(c)} of {len(ids)} ids ({time.time()-t:.0f}s)", file=sys.stderr)
    return c


def load_region(name, cfg, args):
    """Observed nodes + per-node bitmask of OSM stop-cause events within --event-m of the node."""
    from pyproj import Transformer
    from shapely import STRtree, points
    df = pd.read_csv(ROOT / cfg["obs"])
    ev = pd.read_csv(ROOT / cfg["events"], usecols=["node_id", "cause"]).drop_duplicates()
    coords = node_coords(ROOT / cfg["pbf"], set(ev.node_id), ROOT / f"data/osm/event_node_coords_{name}.csv")
    ev = ev.merge(coords, on="node_id", how="inner")
    lcp = level_crossing_points(ROOT / cfg["pbf"])
    lc = pd.DataFrame(lcp, columns=["node_id", "lon", "lat"]).assign(cause="level_crossing")
    ev = pd.concat([ev, lc], ignore_index=True)
    tr = Transformer.from_crs("EPSG:4326", cfg["crs"], always_xy=True)
    ex, ey = tr.transform(ev.lon.values, ev.lat.values)
    ev_tree = STRtree(points(ex, ey))
    x, y = tr.transform(df.lon.values, df.lat.values)
    npts = points(x, y)
    bit = {c: 1 << i for i, c in enumerate(CLASSES[:-1])}
    evbit = ev.cause.map(bit).values
    mask = np.zeros(len(df), dtype=np.int64)
    qi, ti = ev_tree.query(npts, predicate="dwithin", distance=args.event_m)
    np.bitwise_or.at(mask, qi, evbit[ti])
    df = df.assign(x=x, y=y, cause_mask=mask)
    return df, {"level_crossings_in_pbf": len(lc), "event_nodes": len(coords)}


def cluster_units(df, link_m, cluster):
    from shapely import STRtree, points
    pts = points(df.x.values, df.y.values)
    tree = STRtree(pts)
    if cluster == "leader":
        # bounded-diameter (<= 2*link_m) leader clustering, seeds in descending passes order
        order = np.lexsort((-df.stops.values, -df.passes.values))
        root = np.full(len(df), -1)
        for i in order:
            if root[i] >= 0:
                continue
            for j in tree.query(pts[i], predicate="dwithin", distance=link_m):
                if root[j] < 0:
                    root[j] = i
        return root
    a, b = tree.query(pts, predicate="dwithin", distance=link_m)
    parent = np.arange(len(df))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, j in zip(a, b):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj
    return np.array([find(i) for i in range(len(df))])


def region_units(name, df, extra, cluster, link_m):
    root = cluster_units(df, link_m, cluster)
    df = df.assign(unit=root)
    rows = []
    for _, g in df.groupby("unit"):
        passes = int(g.passes.max())  # max over member nodes (ride passes are not recounted from tracks)
        raw_stops = int(g.stops.sum())
        stops = min(raw_stops, passes)
        stopsec = float((g.stops * g.mean_stop_s.fillna(0)).sum())
        mean_s = stopsec / raw_stops if raw_stops else float("nan")
        rep = g.loc[g.passes.idxmax()]
        m = int(np.bitwise_or.reduce(g.cause_mask.values))
        causes = [c for i, c in enumerate(CLASSES[:-1]) if m >> i & 1]
        cls = causes[0] if causes else "midway"  # CLASSES is in precedence order
        gx, gy = g.x.values, g.y.values
        diam = float(np.hypot(gx[:, None] - gx[None, :], gy[:, None] - gy[None, :]).max()) if len(g) > 1 else 0.0
        rows.append({"region": name, "rep_node": int(rep.node_id), "lat": float(rep.lat), "lon": float(rep.lon),
                     "n_nodes": len(g), "diameter_m": diam, "passes": passes, "stops": stops, "raw_stops": raw_stops,
                     "mean_stop_s": mean_s, "stop_seconds": mean_s * stops if stops else 0.0,
                     "cls": cls, "causes": ",".join(causes), "members": "|".join(map(str, g.node_id))})
    units = pd.DataFrame(rows).reset_index(drop=True)
    units.insert(1, "unit_id", np.arange(len(units)))
    collapse = {"nodes": len(df), "units": len(units), "multi_units": int((units.n_nodes > 1).sum()),
                "max_nodes": int(units.n_nodes.max()), "max_diameter_m": float(units.diameter_m.max()),
                "p99_diameter_m": float(units.diameter_m.quantile(0.99)),
                "stops_raw": int(df.stops.sum()), "stops_capped": int(units.stops.sum()),
                "level_crossing_units": int((units.cls == "level_crossing").sum()), **extra}
    return units, collapse


# ----------------------------------------------------------------------------- tables
def class_table(units, min_passes):
    u = units[units.passes >= min_passes]
    rows = []
    for c in CLASSES:
        g = u[u.cls == c]
        n, k = int(g.passes.sum()), int(g.stops.sum())
        lo, hi = wilson(k, n)
        ss = float(g.stop_seconds.sum())
        rows.append({"cls": c, "units": len(g), "passes": n, "stops": k, "p_stop": (k / n if n else float("nan")),
                     "ci_lo": lo, "ci_hi": hi, "mean_stop_s": (ss / k if k else float("nan")),
                     "stop_s_per_pass": (ss / n if n else float("nan")),
                     "share_of_stops": (k / u.stops.sum() if u.stops.sum() else float("nan")),
                     "under_powered": n < 30})
    return pd.DataFrame(rows)


def summary_numbers(units, min_passes_pr=5):
    allu = units
    tot = int(allu.stops.sum())
    expl = int(allu[~allu.cls.isin(["midway", "yield_equal"])].stops.sum())
    u = units[units.passes >= min_passes_pr]
    pred = u.cls.isin(CAUSE_CLASSES)
    out = {"stops_total": tot, "stops_explained": expl,
           "explained_fraction": expl / tot if tot else float("nan"), "units_total": len(allu)}
    for thr in (0.5, 0.25):
        act = (u.stops / u.passes) >= thr
        tp = int((pred & act).sum())
        out[f"tp_{thr}"] = tp
        out[f"pred_pos_{thr}"] = int(pred.sum())
        out[f"act_pos_{thr}"] = int(act.sum())
        out[f"precision_{thr}"] = tp / pred.sum() if pred.sum() else float("nan")
        out[f"recall_{thr}"] = tp / act.sum() if act.sum() else float("nan")
    out["units_ge5"] = len(u)
    return out


# ----------------------------------------------------------------------------- unexplained
def osm_evidence(pbf, targets, radius=40.0):
    """targets: list of (key, lat, lon). Returns key -> dict(nodes=[...], ways=[...])."""
    import osmium
    lat0 = np.array([t[1] for t in targets])
    lon0 = np.array([t[2] for t in targets])
    coslat = np.cos(np.radians(lat0))
    keys = [t[0] for t in targets]
    ev = {k: {"nodes": {}, "ways": {}} for k in keys}
    NODEKEYS = ("highway", "amenity", "shop", "railway", "tourism", "barrier", "traffic_calming", "leisure",
                "crossing", "public_transport")

    def dist(lat, lon):
        return np.hypot((lat - lat0) * 111320.0, (lon - lon0) * 111320.0 * coslat)
    t = time.time()
    fp = osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY).with_locations().with_filter(
        osmium.filter.KeyFilter(*NODEKEYS))
    for o in fp:
        if o.is_node():
            if not o.location.valid():
                continue
            d = dist(o.location.lat, o.location.lon)
            hit = np.nonzero(d <= radius)[0]
            if len(hit):
                tg = {k: v for k, v in ((k, o.tags.get(k)) for k in NODEKEYS) if v}
                for i in hit:
                    ev[keys[i]]["nodes"][o.id] = (round(float(d[i])), tg)
        elif o.is_way() and "highway" in o.tags:
            try:
                la = np.array([n.lat for n in o.nodes])
                lo = np.array([n.lon for n in o.nodes])
            except osmium.InvalidLocationError:
                continue
            # vertex distance (vertices can be > 40 m apart on long straights: also test interpolated points)
            if len(la) > 1:
                fr = np.linspace(0, 1, 5)[1:-1]
                la = np.concatenate([la, *[la[:-1] + (la[1:] - la[:-1]) * f for f in fr]])
                lo = np.concatenate([lo, *[lo[:-1] + (lo[1:] - lo[:-1]) * f for f in fr]])
            if la.max() < lat0.min() - 0.001 or la.min() > lat0.max() + 0.001:
                continue
            for i in range(len(keys)):
                dd = np.hypot((la - lat0[i]) * 111320.0, (lo - lon0[i]) * 111320.0 * coslat[i]).min()
                if dd <= radius:
                    ev[keys[i]]["ways"][o.id] = (round(float(dd)), o.tags.get("highway"), o.tags.get("name") or o.tags.get("ref") or "",
                                                 o.tags.get("maxspeed", ""), o.tags.get("oneway", ""))
    print(f"  evidence pass {time.time()-t:.0f}s", file=sys.stderr)
    return ev


def evidence_text(e):
    parts = []
    for nid, (d, tg) in sorted(e["nodes"].items(), key=lambda kv: kv[1][0]):
        parts.append(f"node {nid} {d}m " + ",".join(f"{k}={v}" for k, v in tg.items()))
    return "; ".join(parts)


def ways_text(e):
    parts = []
    for wid, (d, hw, nm, ms, ow) in sorted(e["ways"].items(), key=lambda kv: kv[1][0]):
        parts.append(f"{hw}{(' ' + nm) if nm else ''}{(' ms' + ms) if ms else ''}{(' ow=' + ow) if ow else ''} ({d}m)")
    return "; ".join(parts)


# ----------------------------------------------------------------------------- output
VARIANTS = {"leader20": ("leader", 20.0), "leader25": ("leader", 25.0), "leader30": ("leader", 30.0),
            "single20": ("single", 20.0)}
HEADLINE = "leader25"


def weights300(t):
    """Relative cost weights: signals = 300, net of the mid-way background stop-seconds per pass."""
    sps = t.set_index("cls").stop_s_per_pass
    bg, sg = sps["midway"], sps["signal"]
    return {c: max(0.0, 300.0 * (sps[c] - bg) / (sg - bg)) if not math.isnan(sps[c]) else float("nan") for c in sps.index}


def unit_export(units, path):
    d = units
    out = pd.DataFrame({"unit_id": d.unit_id, "lat": d.lat.round(6), "lon": d.lon.round(6), "passes": d.passes,
                        "stops": d.stops, "p": (d.stops / d.passes).round(4), "class": d.cls, "n_nodes": d.n_nodes,
                        "diameter_m": d.diameter_m.round(1), "mean_stop_s": d.mean_stop_s.round(1),
                        "member_node_ids": d.members})
    out.to_csv(path, index=False)
    if path.stat().st_size > 1_000_000:  # keep each file < 1 MB: drop single-pass units
        out = out[d.passes.values >= 2]
        out.to_csv(path, index=False)
    return len(out), len(units), path.stat().st_size


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--event-m", type=float, default=20.0, help="OSM events within this distance of any member node classify the unit")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--out", default=str(ROOT / "data/samples"))
    ap.add_argument("--no-evidence", action="store_true", help="skip the unexplained-units PBF pass (needs no PBF way scan)")
    ap.add_argument("--json", default=None, help="dump summary numbers as json")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    data = {}
    for name, cfg in REGIONS.items():
        data[name] = load_region(name, cfg, args)
    res = {}  # variant -> region -> (units, collapse)
    for v, (cl, r) in VARIANTS.items():
        res[v] = {n: region_units(n, data[n][0], data[n][1], cl, r) for n in REGIONS}
        res[v]["combined"] = (pd.concat([res[v]["ireland"][0], res[v]["berlin"][0]], ignore_index=True), None)

    # ---- sensitivity files (all variants)
    srows, crows = [], []
    for v in VARIANTS:
        for name in ("ireland", "berlin", "combined"):
            units = res[v][name][0]
            t5 = class_table(units, 5)
            w = weights300(t5)
            for r in t5.itertuples():
                crows.append({"variant": v, "region": name, "cls": r.cls, "units": r.units, "passes": r.passes,
                              "stops": r.stops, "p_stop": round(r.p_stop, 4), "ci_lo": round(r.ci_lo, 4),
                              "ci_hi": round(r.ci_hi, 4), "stop_s_per_pass": round(r.stop_s_per_pass, 3),
                              "weight_signals_300": round(w[r.cls], 1)})
            sn = summary_numbers(units)
            srows.append({"variant": v, "region": name, **{k: (round(x, 4) if isinstance(x, float) else x) for k, x in sn.items()}})
    pd.DataFrame(crows).to_csv(out / "stop_model_sensitivity_classes.csv", index=False)
    pd.DataFrame(srows).to_csv(out / "stop_model_sensitivity_summary.csv", index=False)

    # ---- headline outputs
    summ = {}
    for name in ("ireland", "berlin", "combined"):
        units = res[HEADLINE][name][0]
        t5, ta = class_table(units, 5), class_table(units, 1)
        t5.insert(0, "table", "ge5_passes")
        ta.insert(0, "table", "all_units")
        r = pd.concat([t5, ta])
        r.insert(0, "region", name)
        r.round(4).to_csv(out / f"stop_model_validation_{name}.csv", index=False)
        summ[name] = {"summary": summary_numbers(units), "t5": t5, "ta": ta, "weights": weights300(t5)}
        if name != "combined":
            summ[name]["collapse"] = res[HEADLINE][name][1]
            kept, tot, size = unit_export(units, out / f"stop_units_{name}.csv")
            print(f"stop_units_{name}.csv: {kept} of {tot} units kept, {size} bytes", file=sys.stderr)

    # ---- unexplained units
    unexp = {}
    for name, cfg in ([] if args.no_evidence else REGIONS.items()):
        u = res[HEADLINE][name][0]
        top = u[u.cls.isin(["midway", "yield_equal"])].sort_values(["stops", "passes"], ascending=[False, False]).head(args.top)
        cache = ROOT / f"data/osm/unexplained_evidence_{HEADLINE}_{name}.pkl"
        import pickle
        key = [(r.rep_node, r.lat, r.lon) for r in top.itertuples()]
        if cache.exists() and pickle.loads(cache.read_bytes())[0] == key:
            ev = pickle.loads(cache.read_bytes())[1]
        else:
            ev = osm_evidence(ROOT / cfg["pbf"], key)
            cache.write_bytes(pickle.dumps((key, ev)))
        rows = []
        for r in top.itertuples():
            e = ev[r.rep_node]
            lab = LABELS.get((name, r.rep_node), ("TODO", ""))
            rows.append({"region": name, "rep_node": r.rep_node, "lat": round(r.lat, 6), "lon": round(r.lon, 6),
                         "cls": r.cls, "n_nodes": r.n_nodes, "passes": r.passes, "stops": r.stops,
                         "mean_stop_s": round(r.mean_stop_s, 1), "nearby_nodes": evidence_text(e),
                         "nearby_ways": ways_text(e), "label": lab[0], "rationale": lab[1]})
        d = pd.DataFrame(rows)
        d.to_csv(out / f"stop_model_unexplained_{name}.csv", index=False)
        unexp[name] = d
        mu = u[u.cls.isin(["midway", "yield_equal"])]
        summ[name]["summary"]["unexplained_stops_total"] = int(mu.stops.sum())
        summ[name]["summary"]["unexplained_top_stops"] = int(top.stops.sum())

    # ---- console report
    for name in ("ireland", "berlin", "combined"):
        s = summ[name]
        print(f"\n### {name} ({HEADLINE})")
        if "collapse" in s:
            print("collapse:", s["collapse"])
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in s["summary"].items()})
        print("weights(signals=300):", {k: None if math.isnan(v) else round(v) for k, v in s["weights"].items()})
        for key in ("t5", "ta"):
            print(f"\n{key}")
            print(s[key].round(3).to_string(index=False))
    for name, d in unexp.items():
        print(f"\n### unexplained {name}")
        print(d.to_string(index=False, max_colwidth=170))
        print("labels:", d.label.value_counts().to_dict())
    if args.json:
        import json
        clean = {n: {"summary": s["summary"], "weights": s["weights"], "collapse": s.get("collapse")} for n, s in summ.items()}
        pathlib.Path(args.json).write_text(json.dumps(clean, indent=1, default=float))


if __name__ == "__main__":
    main()
