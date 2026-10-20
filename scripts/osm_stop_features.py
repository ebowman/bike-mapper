#!/usr/bin/env python3
"""OSM stop-cause features, junction detection and expected stops/km per way.

Usage: uv run scripts/osm_stop_features.py <file.osm.pbf> [--csv OUT.csv] [--signals OUT.csv]

Phases (pyosmium FileProcessor, see osm_tag_coverage.py for the length/haversine convention):
  1. node pass   : collect tagged nodes of interest (signals, stop, give_way, crossing,
                   mini_roundabout, turning_circle, level_crossing, traffic_calming, barrier)
  2. way pass    : for road-cycling ways (classes in RANK, `service` only if `service` tag
                   unset) store class, oneway, roundabout, priority_road, name, length, node refs
  3. in-memory   : numpy node->way membership -> junctions; per-way/per-direction stop events
                   by the yield-inference rule documented in docs/research/osm-stop-features.md

Prints markdown tables to stdout. Writes a per-way CSV (Wicklow bbox only) and a CSV of
signal nodes (all of the extract, for the SCATS recall check).
"""
import argparse
import csv
import math
import sys
import time
from array import array
from collections import Counter, defaultdict

import numpy as np
import osmium

# class hierarchy, highest priority first (rank 0 = highest)
HIER = ["trunk", "primary", "secondary", "tertiary", "unclassified",
        "residential", "living_street", "service"]
RANK = {c: i for i, c in enumerate(HIER)}
BBOX = (-6.5, 53.0, -6.1, 53.3)  # lon_min, lat_min, lon_max, lat_max
R = 6371008.8
NODE_HW = {"traffic_signals", "stop", "give_way", "crossing", "mini_roundabout", "turning_circle"}
KEEP_KEYS = ["highway", "railway", "traffic_calming", "barrier", "direction", "stop:direction",
             "traffic_signals:direction", "give_way:direction", "crossing"]
CAUSES = ["signal", "stop", "give_way", "yield_infer", "yield_equal", "rb_entry", "xing_signal"]
CI = {c: i for i, c in enumerate(CAUSES)}


def hav(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def qual_dir(tags, keys):
    """Return (set of directions {0=fwd,1=bwd}, qualifier_kind) for a node tag dict."""
    for k in keys:
        v = tags.get(k)
        if v:
            v = v.strip().lower()
            if v == "forward":
                return {0}, "forward"
            if v == "backward":
                return {1}, "backward"
            if v in ("both", "all"):
                return {0, 1}, "both"
            return {0, 1}, "other"
    return {0, 1}, None


def oneway_of(t):
    if t.get("junction") in ("roundabout", "circular"):
        return 1
    if t.get("oneway:bicycle") == "no":
        return 0
    v = t.get("oneway")
    if v in ("yes", "true", "1"):
        return 1
    if v in ("-1", "reverse"):
        return -1
    return 0


def pass_nodes(path):
    nodes = {}
    fp = osmium.FileProcessor(path, osmium.osm.NODE).with_filter(osmium.filter.EmptyTagFilter())
    for n in fp:
        t = n.tags
        hw = t.get("highway")
        if hw in NODE_HW or t.get("railway") == "level_crossing" or "traffic_calming" in t or "barrier" in t:
            d = {k: t[k] for k in KEEP_KEYS if k in t}
            nodes[n.id] = (n.location.lon, n.location.lat, d)
    return nodes


class Ways:
    def __init__(self):
        self.id, self.rank, self.ow, self.rb, self.prio = [], [], [], [], []
        self.name, self.hw, self.km, self.off = [], [], [], []
        self.mid = []
        self.refs = array("q")
        self.lons = array("d")
        self.lats = array("d")
        self.rb_all_n = 0
        self.rb_all_km = 0.0
        self.rb_by_value = Counter()


def pass_ways(path):
    W = Ways()
    fp = (osmium.FileProcessor(path, osmium.osm.NODE | osmium.osm.WAY).with_locations()
          .with_filter(osmium.filter.KeyFilter("highway")))
    for w in fp:
        if not w.is_way():
            continue
        t = w.tags
        hw = t.get("highway")
        jn = t.get("junction")
        base = hw[:-5] if (hw or "").endswith("_link") else hw  # *_link ways take the parent's class
        if base not in RANK:
            continue
        if hw == "service" and "service" in t:
            continue
        pts = []
        refs = []
        for n in w.nodes:
            if n.location.valid():
                pts.append((n.lon, n.lat))
                refs.append(n.ref)
        if len(refs) < 2:
            continue
        L = sum(hav(*pts[i], *pts[i + 1]) for i in range(len(pts) - 1)) / 1000.0
        isrb = jn in ("roundabout", "circular")
        if isrb:
            W.rb_all_n += 1
            W.rb_all_km += L
            W.rb_by_value[jn] += 1
        W.id.append(w.id)
        W.rank.append(RANK[base])
        W.hw.append(hw)
        W.ow.append(oneway_of(t))
        W.rb.append(isrb)
        W.prio.append(t.get("priority_road") in ("designated", "yes"))
        W.name.append(t.get("name") or t.get("ref") or "")
        W.km.append(L)
        W.off.append(len(W.refs))
        W.refs.extend(refs)
        W.lons.extend(p[0] for p in pts)
        W.lats.extend(p[1] for p in pts)
        W.mid.append(pts[len(pts) // 2])
    return W


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pbf")
    ap.add_argument("--csv", default="data/samples/stops_per_km_wicklow.csv")
    ap.add_argument("--full-csv", default="data/osm/stops_per_km_wicklow_full.csv",
                    help="unfiltered per-way CSV (gitignored); --csv drops service ways and ways < 50 m")
    ap.add_argument("--no-attribute", action="store_true",
                    help="disable approach-node attribution (reproduces the double-counting 'before' numbers)")
    ap.add_argument("--signals", default="data/osm/signals_ireland.csv")
    ap.add_argument("--bbox", default=None, help="lon_min,lat_min,lon_max,lat_max (default Wicklow)")
    ap.add_argument("--report", default=None, help="also write the markdown output here")
    a = ap.parse_args()
    out = []
    global BBOX
    if a.bbox:
        BBOX = tuple(float(x) for x in a.bbox.split(","))

    def P(s=""):
        print(s)
        out.append(s)

    T0 = time.time()
    nodes = pass_nodes(a.pbf)
    t1 = time.time()
    W = pass_ways(a.pbf)
    t2 = time.time()
    nW = len(W.id)
    lens = np.diff(np.array(W.off + [len(W.refs)], dtype=np.int64))
    off = np.array(W.off, dtype=np.int64)
    refs = np.frombuffer(W.refs, dtype=np.int64)
    rank = np.array(W.rank, dtype=np.int8)
    widx = np.repeat(np.arange(nW, dtype=np.int64), lens)
    pos = np.arange(len(refs), dtype=np.int64) - np.repeat(off, lens)
    kmw = np.array(W.km)

    # ---- junctions: distinct (node, way) pairs
    order = np.lexsort((widx, refs))
    sn, sw = refs[order], widx[order]
    keep = np.ones(len(sn), dtype=bool)
    keep[1:] = (sn[1:] != sn[:-1]) | (sw[1:] != sw[:-1])
    kn, kw = sn[keep], sw[keep]
    starts = np.flatnonzero(np.r_[True, kn[1:] != kn[:-1]])
    unodes = kn[starts]
    cnt = np.diff(np.r_[starts, len(kn)])
    krank = rank[kw]
    hi = np.minimum.reduceat(krank, starts)
    lo = np.maximum.reduceat(krank, starts)
    isj = cnt >= 2
    jnodes = unodes[isj]
    # plain split = exactly 2 ways, same class, node is an end vertex of both (way merely split)
    endp = ((pos == 0) | (pos == lens[widx] - 1))[order]
    starts_all = np.flatnonzero(np.r_[True, sn[1:] != sn[:-1]])
    occ_cnt = np.diff(np.r_[starts_all, len(sn)])
    endsum = np.add.reduceat(endp.astype(np.int64), starts_all)
    split = isj & (cnt == 2) & (occ_cnt == 2) & (endsum == 2) & (hi == lo)
    isjr = isj & ~split  # "real" junctions used for density tables

    # ---- node tallies
    road_nodes = unodes  # nodes on any road-cycling way
    nid_arr = np.array(list(nodes.keys()), dtype=np.int64)
    in_road = np.isin(nid_arr, road_nodes)
    road_flag = dict(zip(nid_arr.tolist(), in_road.tolist()))

    cnt_all, cnt_road = Counter(), Counter()
    qual = defaultdict(Counter)
    totals = Counter()
    crossing_vals = Counter()
    calming = Counter()
    barrier = Counter()
    for nid, (lon, lat, d) in nodes.items():
        hw = d.get("highway")
        r = road_flag[nid]
        keyset = []
        if hw in NODE_HW:
            keyset.append("highway=" + hw)
        if d.get("railway") == "level_crossing":
            keyset.append("railway=level_crossing")
        if "traffic_calming" in d:
            keyset.append("traffic_calming=*")
            if r:
                calming[d["traffic_calming"]] += 1
        if "barrier" in d:
            keyset.append("barrier=*")
            if r:
                barrier[d["barrier"]] += 1
        for k in keyset:
            cnt_all[k] += 1
            if r:
                cnt_road[k] += 1
        if hw == "crossing":
            crossing_vals[d.get("crossing", "(no crossing tag)") + (" [on road]" if r else " [off road]")] += 1
        if hw in ("traffic_signals", "stop", "give_way"):
            totals[hw] += 1
            qk = ["direction", hw + ":direction"] if hw != "traffic_signals" else ["direction", "traffic_signals:direction"]
            if hw == "give_way":
                qk = ["direction", "give_way:direction"]
            present = [k for k in qk if k in d]
            if present:
                qual[hw]["any"] += 1
                for k in present:
                    qual[hw][k] += 1
                v = d[present[0]].lower()
                qual[hw]["val:" + (v if v in ("forward", "backward", "both") else "other")] += 1

    # ---- signals CSV (for SCATS recall)
    with open(a.signals, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["node_id", "kind", "lon", "lat", "on_road_way"])
        for nid, (lon, lat, d) in nodes.items():
            if d.get("highway") == "traffic_signals":
                wr.writerow([nid, "signals", lon, lat, int(road_flag[nid])])
            elif d.get("highway") == "crossing" and d.get("crossing") == "traffic_signals":
                wr.writerow([nid, "xing_signals", lon, lat, int(road_flag[nid])])

    # ---- inference over occurrences at junction nodes or explicit stop-cause nodes
    def explicit_cause(d):
        hw = d.get("highway")
        if hw == "traffic_signals":
            return "signal", ["traffic_signals:direction", "direction"]
        if hw == "stop":
            return "stop", ["stop:direction", "direction"]
        if hw == "give_way":
            return "give_way", ["give_way:direction", "direction"]
        if hw == "mini_roundabout":
            return "rb_entry", None
        if hw == "crossing" and d.get("crossing") == "traffic_signals":
            return "xing_signal", ["traffic_signals:direction", "direction"]
        return None, None

    expl = {}
    ped_cross_ways = Counter()  # way idx -> count (crossings w/o signals; not in estimate)
    for nid, (lon, lat, d) in nodes.items():
        c, qk = explicit_cause(d)
        if c:
            expl[nid] = (c, qk, d)
    interesting = np.array(list(expl.keys()) + [n for n, (_, _, d) in nodes.items()
                                                 if d.get("highway") == "crossing" and n not in expl],
                           dtype=np.int64)
    selmask = np.isin(refs, jnodes) | np.isin(refs, interesting)
    sel = np.flatnonzero(selmask)
    sel = sel[np.argsort(refs[sel], kind="stable")]
    sel_nodes = refs[sel].tolist()
    sel_w = widx[sel].tolist()
    sel_p = pos[sel].tolist()
    rb_nodes = set(refs[np.repeat(np.array(W.rb), lens)].tolist())
    ev = np.zeros((nW, 2, len(CAUSES)))
    flags = Counter()
    ow = W.ow
    wrank = W.rank
    wprio = W.prio
    wrb = W.rb
    lens_l = lens.tolist()
    # ---- approach-node attribution: explicit signal/stop/give_way nodes that are NOT junction nodes are
    # attributed to the junction they approach (walk <= CAP m along the way in the direction of travel;
    # else nearest junction on the way within CAP m; else standalone) and that (junction, way, dir) is
    # marked controlled so inference is suppressed there.
    CAP = 60.0
    jset = set(jnodes.tolist())
    controlled = set()
    attr = Counter()
    appr_ids = np.array([nid for nid, (c, _, _) in expl.items()
                         if c in ("signal", "stop", "give_way") and nid not in jset], dtype=np.int64)
    amask = np.isin(refs, appr_ids)
    offl = W.off
    lons, lats = W.lons, W.lats
    attr_nodes = set()
    for gi in np.flatnonzero(amask).tolist():
        nid = int(refs[gi])
        w, p = int(widx[gi]), int(pos[gi])
        cause, qk, tg = expl[nid]
        ds, _ = qual_dir(tg, qk)
        dirs = set(ds)
        if ow[w] == 1:
            dirs &= {0}
        elif ow[w] == -1:
            dirs &= {1}
        attr_nodes.add(nid)
        base_i = offl[w]
        nl = lens_l[w]

        def scan(step, p=p, nl=nl, base_i=base_i):
            dist, q = 0.0, p
            while 0 <= q + step < nl:
                a_, b_ = base_i + q, base_i + q + step
                dist += hav(lons[a_], lats[a_], lons[b_], lats[b_])
                if dist > CAP:
                    return None
                q += step
                if int(refs[b_]) in jset:
                    return int(refs[b_]), dist
            return None
        for d in dirs:
            fwd = scan(1 if d == 0 else -1)
            if fwd:
                kind, j = "walk", fwd[0]
            else:
                back = scan(-1 if d == 0 else 1)
                if back:
                    kind, j = "nearest", back[0]
                else:
                    kind, j = "standalone", None
            attr[kind] += 1
            if j is not None and not a.no_attribute:
                controlled.add((j, w, d))
    suppressed = Counter()
    i, n = 0, len(sel_nodes)
    while i < n:
        j = i
        nid = sel_nodes[i]
        while j < n and sel_nodes[j] == nid:
            j += 1
        occ = list(zip(sel_w[i:j], sel_p[i:j]))
        i = j
        e = expl.get(nid)
        d_tags = nodes[nid][2] if nid in nodes else {}
        if e is None and d_tags.get("highway") == "crossing":
            for w, p in occ:
                ped_cross_ways[w] += 1
        ways = {w for w, _ in occ}
        isjunction = len(ways) >= 2
        hasrb = nid in rb_nodes
        # continuation: exactly two ways, each only touching the node with an end vertex
        cont = (len(ways) == 2 and all(p == 0 or p == lens_l[w] - 1 for w, p in occ))
        if e is None and not isjunction:
            continue
        for w, p in occ:
            dirs = set()
            if p == 0 or p == lens_l[w] - 1:
                if p == 0:
                    dirs.add(1)
                if p == lens_l[w] - 1:
                    dirs.add(0)
            else:
                dirs = {0, 1}
            if ow[w] == 1:
                dirs &= {0}
            elif ow[w] == -1:
                dirs &= {1}
            for d in dirs:
                done = False
                if e is not None:
                    cause, qk = e[0], e[1]
                    if qk is None:
                        ok, qkind = True, None
                    else:
                        ds, qkind = qual_dir(e[2], qk)
                        ok = d in ds
                    if ok:
                        ev[w, d, CI[cause]] += 1
                        if cause == "signal" and qkind is None and ow[w] == 0:
                            flags["signal_two_way_unqualified_event"] += 1
                        done = True
                if done:
                    continue
                if not isjunction:
                    continue
                if (nid, w, d) in controlled:
                    suppressed["junction approaches suppressed"] += 1
                    continue
                if wrb[w]:
                    continue  # circulating traffic has priority
                if hasrb:
                    ev[w, d, CI["rb_entry"]] += 1
                    continue
                if cont:
                    continue
                others = ways - {w}
                if wprio[w] and not any(wprio[o] for o in others):
                    continue
                if (not wprio[w]) and any(wprio[o] for o in others):
                    ev[w, d, CI["yield_infer"]] += 1
                    continue
                best = min(wrank[o] for o in others)
                if wrank[w] > best:
                    ev[w, d, CI["yield_infer"]] += 1
                elif wrank[w] == best:
                    ev[w, d, CI["yield_equal"]] += 0.5
    t3 = time.time()

    # signal-node event semantics flag: count signal nodes on two-way roads w/o qualifier
    sig_unq = sum(1 for nid, (c, qk, d) in expl.items()
                  if c == "signal" and road_flag.get(nid) and qual_dir(d, qk)[1] is None)

    # ---- output
    P(f"<!-- {a.pbf}: node pass {t1-T0:.0f}s, way pass {t2-t1:.0f}s, inference {t3-t2:.0f}s, "
      f"total {t3-T0:.0f}s; {nW} road-cycling ways, {len(nodes)} tagged nodes, "
      f"{len(jnodes)} junction nodes -->\n")
    P("### Node feature counts (whole extract; 'on road way' = node is on a road-cycling way)\n")
    P("| feature | all nodes | on road way | on road %  |\n|---|---|---|---|")
    for k in ["highway=traffic_signals", "highway=stop", "highway=give_way", "highway=crossing",
              "highway=mini_roundabout", "highway=turning_circle", "railway=level_crossing",
              "traffic_calming=*", "barrier=*"]:
        c, r = cnt_all[k], cnt_road[k]
        P(f"| {k} | {c} | {r} | {100*r/c if c else 0:.0f} |")
    P(f"\nWays with junction=roundabout|circular (all highway classes in scope): {W.rb_all_n} "
      f"({dict(W.rb_by_value)}), {W.rb_all_km:.0f} km.\n")
    P("### Crossing nodes by crossing=* value\n")
    P("| crossing value | nodes |\n|---|---|")
    for v, c in crossing_vals.most_common(14):
        P(f"| {v} | {c} |")
    P("\n### Direction qualifiers on stop-cause nodes\n")
    P("| node type | nodes | with any qualifier | % | direction=* | <type>:direction | forward | backward | both | other |\n"
      "|---|---|---|---|---|---|---|---|---|---|")
    for hw in ("traffic_signals", "stop", "give_way"):
        q = qual[hw]
        spec = {"traffic_signals": "traffic_signals:direction", "stop": "stop:direction",
                "give_way": "give_way:direction"}[hw]
        P(f"| {hw} | {totals[hw]} | {q['any']} | {100*q['any']/max(totals[hw],1):.1f} | {q['direction']} | "
          f"{q[spec]} | {q['val:forward']} | {q['val:backward']} | {q['val:both']} | {q['val:other']} |")
    P(f"\nSignal nodes on road ways with no direction qualifier (counted for both directions on two-way ways, "
      f"flagged assumption): {sig_unq}.\n")
    P("### Approach-node attribution of explicit signal/stop/give_way nodes\n")
    nj = sum(1 for nid, (c, _, _) in expl.items() if c in ("signal", "stop", "give_way")
             and nid in jset and road_flag.get(nid))
    P(f"Mode: {'DISABLED (--no-attribute, before-fix behaviour)' if a.no_attribute else 'enabled'}. Explicit "
      f"signal/stop/give_way nodes on road ways: on a junction node {nj}; on an approach (non-junction) node "
      f"{len(attr_nodes)}. Approach events (node x travel direction): attributed by walking <= {CAP:.0f} m "
      f"along the way in the direction of travel to the next junction: {attr['walk']}; attributed to the nearest "
      f"junction within {CAP:.0f} m behind (no junction ahead within the cap): {attr['nearest']}; standalone "
      f"(no junction within {CAP:.0f} m): {attr['standalone']}. Junction approaches whose inferred yield / "
      f"equal-class term was suppressed: {suppressed['junction approaches suppressed']}.\n")
    P("traffic_calming on road ways (top 8): " + ", ".join(f"{k}={v}" for k, v in calming.most_common(8)))
    P("\nbarrier on road ways (top 8): " + ", ".join(f"{k}={v}" for k, v in barrier.most_common(8)))

    P("\n### Junction nodes and density by highway class\n")
    P("Junction = node shared by >= 2 distinct road-cycling ways. 'Present' = junctions where the class "
      "meets; density = present / km of that class (km = sum of way lengths).\n")
    P("| class | km | ways | junctions present | per km | as highest | as lowest |\n|---|---|---|---|---|---|---|")
    kmc = np.bincount(rank, weights=kmw, minlength=len(HIER))
    wc = np.bincount(rank, minlength=len(HIER))
    inj = np.add.reduceat(np.stack([(krank == c).astype(np.int32) for c in range(len(HIER))]),
                          starts, axis=1)
    for c, name in enumerate(HIER):
        pres = int(((inj[c] > 0) & isjr).sum())
        P(f"| {name} | {kmc[c]:.0f} | {wc[c]} | {pres} | {pres/kmc[c] if kmc[c] else 0:.2f} | "
          f"{int(((hi == c) & isjr).sum())} | {int(((lo == c) & isjr).sum())} |")
    P(f"| ALL | {kmc.sum():.0f} | {nW} | {int(isjr.sum())} | {isjr.sum()/kmc.sum():.2f} | | |")
    P(f"\nJunction nodes: {int(isj.sum())} shared by >= 2 ways, of which {int(split.sum())} are plain splits "
      f"(exactly 2 ways of the same class, end vertex of both) and are excluded from the table above, leaving "
      f"{int(isjr.sum())}. Density of ALL nodes shared by >= 2 ways (splits kept): {isj.sum()/kmc.sum():.2f}/km. "
      f"Way classes include `*_link` ways under their parent's class.\n")
    P("\n#### Junction nodes by (highest class, lowest class) meeting\n")
    P("| highest \\ lowest | " + " | ".join(HIER) + " |\n|---|" + "---|" * len(HIER))
    for h in range(len(HIER)):
        row = [int(((hi == h) & (lo == l) & isjr).sum()) for l in range(len(HIER))]
        P(f"| {HIER[h]} | " + " | ".join(str(x) for x in row) + " |")

    # ---- per-way stops
    tot = ev.sum(axis=2)  # (nW, 2)
    travel = np.ones((nW, 2), dtype=bool)
    owa = np.array(W.ow)
    travel[owa == 1, 1] = False
    travel[owa == -1, 0] = False
    lon_mid = np.array([m[0] for m in W.mid])
    lat_mid = np.array([m[1] for m in W.mid])
    inb = (lon_mid >= BBOX[0]) & (lon_mid <= BBOX[2]) & (lat_mid >= BBOX[1]) & (lat_mid <= BBOX[3])
    bi = np.flatnonzero(inb)
    n_sample = 0
    with open(a.csv, "w", newline="") as f, open(a.full_csv, "w", newline="") as ff:
        wr, wf = csv.writer(f), csv.writer(ff)
        hdr = ["way_id", "name", "highway", "length_km", "stops_fwd", "stops_bwd",
               "stops_per_km_fwd", "stops_per_km_bwd"]
        wr.writerow(hdr)
        wf.writerow(hdr)
        for w in bi:
            L = kmw[w]
            row = [W.id[w], W.name[w], W.hw[w], f"{L:.3f}"]
            for d in (0, 1):
                row.append(f"{tot[w, d]:.1f}" if travel[w, d] else "")
            for d in (0, 1):
                row.append(f"{tot[w, d]/L:.2f}" if travel[w, d] and L > 0 else "")
            wf.writerow(row)
            if W.hw[w] != "service" and L >= 0.05:  # sample CSV: no service ways, no ways < 50 m
                wr.writerow(row)
                n_sample += 1

    P(f"\n### Expected stops/km per way, Wicklow bbox (lon {BBOX[0]}..{BBOX[2]}, lat {BBOX[1]}..{BBOX[3]})\n")
    P(f"{len(bi)} ways (selected by mid-vertex in bbox); sample CSV `{a.csv}` has {n_sample} ways (service ways "
      f"and ways < 50 m dropped; the full set is `{a.full_csv}`, gitignored). All tables below use all {len(bi)} ways. Statistics over (way, travel direction) "
      "samples for ways >= 0.1 km; 'pooled' = sum stops / sum km over all ways of the class.\n")
    P("| class | ways | km | median stops/km | p90 stops/km | pooled stops/km | share of ways with 0 stops |\n|---|---|---|---|---|---|---|")
    for c, name in enumerate(HIER):
        idx = bi[rank[bi] == c]
        if not len(idx):
            continue
        vals = []
        for w in idx:
            if kmw[w] >= 0.1:
                for d in (0, 1):
                    if travel[w, d]:
                        vals.append(tot[w, d] / kmw[w])
        pk = sum(tot[w, d] * 1.0 for w in idx for d in (0, 1) if travel[w, d])
        pl = sum(kmw[w] * sum(travel[w]) for w in idx)
        vv = np.array(vals) if vals else np.array([0.0])
        P(f"| {name} | {len(idx)} | {kmw[idx].sum():.0f} | {np.median(vv):.2f} | {np.percentile(vv,90):.2f} | "
          f"{pk/max(pl,1e-9):.2f} | {100*(vv==0).mean():.0f}% |")
    # cause breakdown (bbox)
    P("\nBreakdown of expected stops by cause in bbox (sum over travel directions; per-direction km pooled):\n")
    P("| cause | events | per km |\n|---|---|---|")
    pl_all = sum(kmw[w] * sum(travel[w]) for w in bi)
    for c in CAUSES:
        s = sum(ev[w, d, CI[c]] for w in bi for d in (0, 1) if travel[w, d])
        P(f"| {c} | {s:.0f} | {s/max(pl_all,1e-9):.3f} |")
    pedx = sum(ped_cross_ways[w] for w in bi)
    P(f"\nPedestrian crossing nodes (no signals) on bbox road ways, not in estimate: {pedx}.")

    # ---- stretches: chain consecutive same-name ways (shared endpoint node)
    par = {int(w): int(w) for w in bi}

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    endmap = {}
    for w in bi:
        nm = W.name[w]
        if not nm:
            continue
        s = W.off[w]
        for node in (int(W.refs[s]), int(W.refs[s + lens_l[w] - 1])):
            k = (nm, node)
            if k in endmap:
                ra, rb_ = find(int(w)), find(endmap[k])
                if ra != rb_:
                    par[ra] = rb_
            else:
                endmap[k] = int(w)
    comp = defaultdict(list)
    for w in bi:
        comp[find(int(w))].append(int(w))
    rows = []
    for ws in comp.values():
        L = sum(kmw[w] for w in ws)
        st = 0.0
        for w in ws:
            nd = [d for d in (0, 1) if travel[w, d]]
            st += kmw[w] * (sum(tot[w, d] / kmw[w] for d in nd) / len(nd)) if kmw[w] > 0 else 0
        rate = st / L if L else 0
        names = {W.name[w] for w in ws}
        hws = Counter(W.hw[w] for w in ws).most_common(1)[0][0]
        rows.append((L, rate, st, len(ws), (", ".join(sorted(names)) or "(unnamed)"), hws, ws[0]))
    low = sorted([r for r in rows if r[1] < 0.2], key=lambda r: -r[0])[:20]
    P("\n### 20 longest stretches with < 0.2 expected stops/km (Wicklow bbox)\n")
    P("Stretch = connected chain of ways with the same `name` (or `ref` when unnamed) joined at way end-vertices (unnamed ways are single-way "
      "stretches). Rate = direction-averaged expected stops / total length (a stretch is not oriented, so fwd/bwd "
      "are averaged per way).\n")
    P("| # | name | main class | length km | ways | exp. stops | stops/km | first way id |\n|---|---|---|---|---|---|---|---|")
    for k, (L, rate, st, nw, nm, hwc, w0) in enumerate(low, 1):
        P(f"| {k} | {nm} | {hwc} | {L:.1f} | {nw} | {st:.1f} | {rate:.2f} | {W.id[w0]} |")
    if a.report:
        with open(a.report, "w") as f:
            f.write("\n".join(out) + "\n")
    print(f"total wall {time.time()-T0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
