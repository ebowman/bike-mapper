#!/usr/bin/env python3
"""Empirical stop events from ride GPS (FIT / GPX / TCX), snapped to OSM nodes and ways.

Usage:
  uv run scripts/stop_events.py --source eric   # data/rides/*.fit (dedup via index.json)
  uv run scripts/stop_events.py --source osm    # data/gps/osm_trackpoints_p*.gpx (scripts/fetch_osm_traces.py)
  uv run scripts/stop_events.py --selftest      # synthetic GPX/TCX/FIT-less checks of the detector

STOP EVENT (all thresholds are CLI flags; defaults shown):
  slow   : speed < --speed-thr 1.0 m/s sustained >= --min-stop-s 3 s (recorded speed if present, else
           haversine/dt smoothed over 3 points)
  pause  : recording gap > --gap-s 2 s bracketed by FIT `event` timer stop_all/stop ... start messages
           (Edge auto-pause), or a timer stop->start pair > 2 s; duration = the gap
  gap    : unbracketed recording gap in (--gap-s, --data-gap-s 30] s on a regularly recorded file
  A gap > 30 s without timer events is a DATA gap (counted, not a stop). Any gap whose endpoints are
  > --gap-max-disp 100 m apart is a data gap (the rider moved while not recording).
  Events < --merge-s 10 s apart are merged (kind priority pause > gap > slow). Events within
  --end-margin-m 200 m of the ride start/end are discarded. Events longer than --max-stop-s 300 s are
  kind `rest` (reported, excluded from per-node / per-way stop statistics).
"""
import argparse
import csv
import datetime as dt
import glob
import itertools
import json
import math
import pathlib
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import snap

R = 6371008.8
IRELAND = (-10.7, 51.3, -5.3, 55.5)
SEMI = 180.0 / 2 ** 31
BIG_HW = {"motorway", "motorway_link", "trunk", "trunk_link"}


# ---------------------------------------------------------------- parsing
class Stream:
    """Uniform ride stream: arrays t (epoch s), lat, lon, speed (m/s, NaN if absent) + timer events."""

    def __init__(self, t, lat, lon, speed, timer=None, name=""):
        self.t, self.lat, self.lon, self.speed = (np.asarray(a, float) for a in (t, lat, lon, speed))
        self.timer = timer or []  # [(epoch, 'stop'|'start')]
        self.name = name


def hav(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def parse_fit(path):
    import fitdecode
    T, LA, LO, SP, timer = [], [], [], [], []
    with fitdecode.FitReader(str(path)) as fr:
        for fr_ in fr:
            if not isinstance(fr_, fitdecode.FitDataMessage):
                continue
            if fr_.name == "record":
                ts = fr_.get_value("timestamp", fallback=None)
                la = fr_.get_value("position_lat", fallback=None)
                lo = fr_.get_value("position_long", fallback=None)
                if ts is None or la is None or lo is None:
                    continue
                sp = fr_.get_value("enhanced_speed", fallback=None)
                if sp is None:
                    sp = fr_.get_value("speed", fallback=None)
                T.append(ts.replace(tzinfo=dt.UTC).timestamp()); LA.append(la * SEMI); LO.append(lo * SEMI)
                SP.append(float(sp) if sp is not None else math.nan)
            elif fr_.name == "event" and fr_.get_value("event", fallback=None) == "timer":
                et, ts = fr_.get_value("event_type", fallback=None), fr_.get_value("timestamp", fallback=None)
                if ts is not None and et in ("stop_all", "stop", "start"):
                    timer.append((ts.replace(tzinfo=dt.UTC).timestamp(), "start" if et == "start" else "stop"))
    return Stream(T, LA, LO, SP, timer, pathlib.Path(path).stem)


def _ts(s):
    return dt.datetime.fromisoformat(s).timestamp()


def parse_gpx_segments(source):
    """Return list of (name, Stream) per <trkseg> using gpxpy; speed from extensions if present else NaN."""
    import gpxpy
    g = gpxpy.parse(source)
    out = []
    for tr in g.tracks:
        for sg in tr.segments:
            pts = [p for p in sg.points if p.time is not None]
            if not pts:
                continue
            sp = [getattr(p, "speed", None) for p in pts]
            out.append(Stream([p.time.timestamp() for p in pts], [p.latitude for p in pts],
                              [p.longitude for p in pts], [s if s is not None else math.nan for s in sp],
                              name=tr.name or ""))
    return out


def parse_tcx(path):
    ns = {"t": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
    T, LA, LO, SP = [], [], [], []
    for tp in ET.parse(path).getroot().iter(f"{{{ns['t']}}}Trackpoint"):
        tm, pos = tp.find("t:Time", ns), tp.find("t:Position", ns)
        if tm is None or pos is None:
            continue
        T.append(_ts(tm.text)); LA.append(float(pos.find("t:LatitudeDegrees", ns).text))
        LO.append(float(pos.find("t:LongitudeDegrees", ns).text))
        sp = tp.find(".//{*}Speed")
        SP.append(float(sp.text) if sp is not None else math.nan)
    return Stream(T, LA, LO, SP, name=pathlib.Path(path).stem)


def parse_any(path):
    p = str(path).lower()
    if p.endswith(".fit"):
        return [parse_fit(path)]
    if p.endswith(".gpx"):
        return parse_gpx_segments(open(path))
    if p.endswith(".tcx"):
        return [parse_tcx(path)]
    raise ValueError(path)


# ---------------------------------------------------------------- detection
def xy_of(s):
    return snap.project(s.lon, s.lat)


def speeds(s):
    """Recorded speed where present, else 3-point-smoothed haversine speed."""
    n = len(s.t)
    if n < 2:
        return np.zeros(n)
    lo, hi = np.maximum(np.arange(n) - 1, 0), np.minimum(np.arange(n) + 1, n - 1)
    d = hav(s.lat[lo], s.lon[lo], s.lat[hi], s.lon[hi])
    dtm = np.maximum(s.t[hi] - s.t[lo], 1e-3)
    comp = d / dtm
    return np.where(np.isnan(s.speed), comp, s.speed)


def detect(s, speed_thr=1.0, min_stop_s=3.0, merge_s=10.0, end_margin_m=200.0, gap_s=2.0,
           data_gap_s=30.0, gap_max_disp=100.0, run_max_dt=5.0, use_gaps=True, max_stop_s=300.0):
    """Return (events, info). event = dict(t0, t1, dur, lat, lon, kind in pause|gap|slow)."""
    n = len(s.t)
    info = Counter()
    if n < 5:
        return [], info
    order = np.argsort(s.t, kind="stable")
    if not np.all(order == np.arange(n)):
        s = Stream(s.t[order], s.lat[order], s.lon[order], s.speed[order], s.timer, s.name)
    v = speeds(s)
    ev = []
    # slow runs
    slow = v < speed_thr
    i = 0
    while i < n:
        if not slow[i]:
            i += 1; continue
        j = i
        while j + 1 < n and slow[j + 1] and s.t[j + 1] - s.t[j] <= run_max_dt:
            j += 1
        if s.t[j] - s.t[i] >= min_stop_s:
            ev.append({"t0": s.t[i], "t1": s.t[j], "lat": float(np.median(s.lat[i:j + 1])),
                           "lon": float(np.median(s.lon[i:j + 1])), "kind": "slow"})
        i = j + 1
    # gaps
    stops = [t for t, k in s.timer if k == "stop"]
    dts = np.diff(s.t)
    for k in np.where(dts > gap_s)[0]:
        a, b = s.t[k], s.t[k + 1]
        disp = float(hav(s.lat[k], s.lon[k], s.lat[k + 1], s.lon[k + 1]))
        bracketed = any(a - 2 <= t <= b + 2 for t in stops)
        if disp > gap_max_disp:
            info["datagap_moved"] += 1; continue
        if bracketed:
            ev.append({"t0": a, "t1": b, "lat": float(s.lat[k]), "lon": float(s.lon[k]), "kind": "pause"})
        elif dts[k] > data_gap_s:
            info["datagap_unbracketed"] += 1
        elif use_gaps:
            ev.append({"t0": a, "t1": b, "lat": float(s.lat[k]), "lon": float(s.lon[k]), "kind": "gap"})
    # timer stop->start pairs not already covered by a record gap
    tm = sorted(s.timer)
    for (t1, k1), (t2, k2) in itertools.pairwise(tm):
        if k1 == "stop" and k2 == "start" and t2 - t1 > gap_s and not any(e["t0"] - 2 <= t1 <= e["t1"] + 2 for e in ev if e["kind"] == "pause"):
            j = int(np.argmin(np.abs(s.t - t1)))
            if hav(s.lat[j], s.lon[j], s.lat[min(j + 1, n - 1)], s.lon[min(j + 1, n - 1)]) <= gap_max_disp:
                ev.append({"t0": t1, "t1": t2, "lat": float(s.lat[j]), "lon": float(s.lon[j]), "kind": "pause"})
                info["timer_pair_only"] += 1
    # merge
    ev.sort(key=lambda e: e["t0"])
    pri = {"pause": 2, "gap": 1, "slow": 0}
    merged = []
    for e in ev:
        if merged and e["t0"] - merged[-1]["t1"] < merge_s:
            m = merged[-1]
            if pri[e["kind"]] > pri[m["kind"]]:
                m["kind"], m["lat"], m["lon"] = e["kind"], e["lat"], e["lon"]
            m["t1"] = max(m["t1"], e["t1"])
        else:
            merged.append(dict(e))
    # discard near ride start / end
    out = []
    for e in merged:
        e["dur"] = e["t1"] - e["t0"]
        if e["dur"] > max_stop_s:
            e["kind"] = "rest"  # cafe / mechanical / photo stop: reported, excluded from node/way stop statistics
        d0 = float(hav(e["lat"], e["lon"], s.lat[0], s.lon[0]))
        d1 = float(hav(e["lat"], e["lon"], s.lat[-1], s.lon[-1]))
        if min(d0, d1) < end_margin_m:
            info["discarded_end_margin"] += 1; continue
        out.append(e)
    return out, info


def track_km(s):
    if len(s.t) < 2:
        return 0.0
    d = hav(s.lat[:-1], s.lon[:-1], s.lat[1:], s.lon[1:])
    return float(d[d < 200].sum() / 1000)


def median_dt(s):
    return float(np.median(np.diff(s.t))) if len(s.t) > 1 else math.nan


# ---------------------------------------------------------------- selftest
def selftest():
    import tempfile
    t0 = 1_700_000_000
    lat0, lon0 = 53.3, -6.25
    # 400 m east at 5 m/s, 20 s stop, 400 m east, GPX without speed
    rows = []
    x, t = 0.0, 0
    for seg in range(2):
        for _ in range(400 // 5 * 1):
            rows.append((t, x)); x += 5; t += 1
        if seg == 0:
            for _ in range(20):
                rows.append((t, x)); t += 1
    rows += [(t + i, x + 5 * i) for i in range(1, 101)]
    k = 1.0 / (111320 * math.cos(math.radians(lat0)))
    gpx = ('<gpx version="1.1" creator="x" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
           + "".join(f'<trkpt lat="{lat0}" lon="{lon0 + xx * k}"><time>{dt.datetime.fromtimestamp(t0 + tt, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>' for tt, xx in rows)
           + "</trkseg></trk></gpx>")
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "a.gpx"; p.write_text(gpx)
        segs = parse_any(p)
        ev, _ = detect(segs[0])
        assert len(ev) == 1 and ev[0]["kind"] == "slow" and 17 <= ev[0]["dur"] <= 22, ev
        tcx = ('<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"><Activities><Activity><Lap><Track>'
               + "".join(f'<Trackpoint><Time>{dt.datetime.fromtimestamp(t0 + tt, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}</Time><Position><LatitudeDegrees>{lat0}</LatitudeDegrees><LongitudeDegrees>{lon0 + xx * k}</LongitudeDegrees></Position></Trackpoint>' for tt, xx in rows)
               + "</Track></Lap></Activity></Activities></TrainingCenterDatabase>")
        q = pathlib.Path(d) / "a.tcx"; q.write_text(tcx)
        ev2, _ = detect(parse_any(q)[0])
        assert len(ev2) == 1 and ev2[0]["kind"] == "slow", ev2
    # auto-pause gap with timer events
    n = 300
    tt = np.arange(n, dtype=float); tt[150:] += 40
    xx = np.arange(n) * 5.0
    s = Stream(tt, np.full(n, lat0), lon0 + xx * k, np.full(n, 5.0), timer=[(tt[149] + 1, "stop"), (tt[150], "start")])
    ev3, _ = detect(s)
    assert len(ev3) == 1 and ev3[0]["kind"] == "pause" and abs(ev3[0]["dur"] - 41) < 1.5, ev3
    s2 = Stream(tt, np.full(n, lat0), lon0 + xx * k, np.full(n, 5.0))  # unbracketed 41 s -> data gap
    ev4, inf = detect(s2)
    assert not ev4 and inf["datagap_unbracketed"] == 1
    print("selftest OK: GPX(no speed), TCX, bracketed pause, unbracketed data gap")


# ---------------------------------------------------------------- source loading
COUNTRIES = [("Ireland", (-10.7, 51.3, -5.3, 55.5)), ("Slovenia", (13.3, 45.4, 16.6, 46.9)),
             ("Greece", (19.0, 34.8, 30.0, 41.8)), ("Netherlands", (3.3, 50.7, 7.3, 53.6)),
             ("France", (-5.2, 42.3, 8.3, 51.1)), ("Germany", (5.9, 47.2, 15.1, 55.1)),
             ("UK (GB)", (-8.0, 49.8, 2.0, 60.9))]


def country_of(lat, lon):
    for n, b in COUNTRIES:
        if b[0] <= lon <= b[2] and b[1] <= lat <= b[3]:
            return n
    return "other"


def load_eric(a):
    with open(ROOT / "data/rides/index.json") as fh:
        idx = {r["activityId"]: r for r in json.load(fh)}
    cand, dropped = [], []
    for f in sorted(glob.glob(str(ROOT / "data/rides/*.fit"))):
        aid = int(pathlib.Path(f).stem)
        meta = idx.get(aid, {})
        s = parse_fit(f)
        rec = {"id": aid, "meta": meta, "s": s, "edge": str(meta.get("manufacturer", "")).upper() == "GARMIN",
                   "start": _ts(meta["startTimeGMT"].replace(" ", "T") + "Z") if meta.get("startTimeGMT") else (s.t[0] if len(s.t) else 0),
                   "dist": float(meta.get("distance_m") or 0)}
        rec["end"] = rec["start"] + (s.t[-1] - s.t[0] if len(s.t) else 0)
        if len(s.t) < 5:
            dropped.append((aid, "no position records (empty / indoor)")); continue
        if median_dt(s) > 2.0:
            dropped.append((aid, f"smart recording (median dt {median_dt(s):.1f}s)")); continue
        if not (a.inbox[0] <= s.lon[0] <= a.inbox[2] and a.inbox[1] <= s.lat[0] <= a.inbox[3]):
            rec["outside"] = True
        cand.append(rec)
    keep = []
    for r in sorted(cand, key=lambda r: (not r["edge"], r["start"])):
        # bead rule: start +-60 s and distance +-2 %. Extension: also when the time spans overlap > 50 % of the
        # shorter ride (third-party re-uploads of one ride start minutes apart) and distance is within 10 %.
        def is_dup(k, r=r):
            if abs(k["start"] - r["start"]) <= 60 and abs(k["dist"] - r["dist"]) <= 0.02 * max(k["dist"], 1):
                return True
            ov = min(k["end"], r["end"]) - max(k["start"], r["start"])
            short = min(k["end"] - k["start"], r["end"] - r["start"])
            return short > 0 and ov > 0.5 * short and abs(k["dist"] - r["dist"]) <= 0.10 * max(k["dist"], 1)
        dup = next((k for k in keep if is_dup(k)), None)
        if dup:
            dropped.append((r["id"], f"duplicate of {dup['id']}")); continue
        keep.append(r)
    return keep, dropped


def load_osm(a):
    """Merge <trk> by url (traces continue across pages); returns list of (url, Stream)."""
    import gpxpy
    traces = defaultdict(lambda: ([], [], [], []))
    total_pts = ts_pts = total_trk = ts_trk = 0
    seen = set()
    for f in sorted(glob.glob(str(ROOT / "data/gps/osm_trackpoints_p*.gpx"))):
        with open(f) as fh:
            g = gpxpy.parse(fh)
        for ti, tr in enumerate(g.tracks):
            url = tr.link or tr.name or f"{pathlib.Path(f).stem}#{ti}"
            for si, sg in enumerate(tr.segments):
                has = [p for p in sg.points if p.time is not None]
                total_pts += len(sg.points); ts_pts += len(has)
                total_trk += 1; ts_trk += bool(has)
                T, LA, LO, _ = traces[(url if tr.link else f"{f}#{ti}", si)]
                for p in has:
                    k = (url, p.time.timestamp(), round(p.latitude, 6), round(p.longitude, 6))
                    if k in seen:
                        continue
                    seen.add(k)
                    T.append(p.time.timestamp()); LA.append(p.latitude); LO.append(p.longitude)
    out = [(k[0], Stream(*v[:3], [math.nan] * len(v[0]), name=str(k[0]))) for k, v in traces.items() if len(v[0]) >= 5]
    return out, {"total_pts": total_pts, "ts_pts": ts_pts, "total_seg": total_trk, "ts_seg": ts_trk,
                     "n_traces": len(traces), "n_traces_ts": len(out)}


# ---------------------------------------------------------------- analysis
def analyze(items, net, a, label):
    """items: list of (id, Stream). Returns node/way stats + counters."""
    info = Counter()
    per_trace = []
    for tid, s in items:
        ev, inf = detect(s, a.speed_thr, a.min_stop_s, a.merge_s, a.end_margin_m, a.gap_s,
                         a.data_gap_s, a.gap_max_disp, a.run_max_dt, use_gaps=a.source == "eric", max_stop_s=a.max_stop_s)
        info.update(inf)
        x, y = xy_of(s)
        seg, t, _ = net.snap(x, y, a.snap_m)
        node, nd = net.node_of(seg, t, x, y)
        big = np.array([net.hw_of_seg(k) in BIG_HW for k in seg[seg >= 0]]) if (seg >= 0).any() else np.array([])
        per_trace.append((tid, s, ev, seg, t, node, nd, float(big.mean()) if len(big) else 0.0))
    return per_trace, info


def accumulate(rows, net, a):
    node_pass, node_stop, node_dur = Counter(), Counter(), defaultdict(float)
    way_km, way_stop, way_pass = Counter(), Counter(), Counter()
    kinds = Counter(); kind_dur = defaultdict(float)
    capped = 0
    pts_total = pts_snapped = ev_total = ev_snapped = 0
    km = 0.0
    for tid, s, ev, seg, t, node, nd, bigfrac in rows:
        km += track_km(s)
        pts_total += len(seg); pts_snapped += int((seg >= 0).sum())
        # passes (per trace, not per point): node within node_radius of a snapped point
        ok = (seg >= 0) & (nd <= a.node_radius)
        for nid in set(node[ok].tolist()):
            node_pass[nid] += 1
        # way km / passes per direction
        x, y = xy_of(s)
        n = len(x)
        step = np.zeros(n)
        step[1:] = np.hypot(np.diff(x), np.diff(y))
        lo, hi = np.maximum(np.arange(n) - 1, 0), np.minimum(np.arange(n) + 1, n - 1)
        mvx, mvy = x[hi] - x[lo], y[hi] - y[lo]
        sg = np.where(seg >= 0, seg, 0)
        fwd = (mvx * (net.bx[sg] - net.ax[sg]) + mvy * (net.by[sg] - net.ay[sg])) >= 0
        wi = net.way_of_seg[sg]
        seen = set()
        for i in np.where((seg >= 0) & (step < 100) & (step > 0))[0]:
            key = (net.way_ids[wi[i]], 0 if fwd[i] else 1)
            way_km[key] += step[i] / 1000
            if key not in seen:
                seen.add(key); way_pass[key] += 1
        # events
        stopped_here = set()  # one stop per ride per node (probability <= 1)
        for e in ev:
            kinds[e["kind"]] += 1; kind_dur[e["kind"]] += e["dur"]
            if e["kind"] == "rest":
                continue
            ev_total += 1
            ex, ey = snap.project([e["lon"]], [e["lat"]])
            sgm, tt, _ = net.snap(ex, ey, a.snap_m)
            if sgm[0] < 0:
                continue
            ev_snapped += 1
            nid, ndist = net.node_of(sgm, tt, ex, ey)
            j = int(np.argmin(np.abs(s.t - e["t0"])))
            lo_, hi_ = max(j - 1, 0), min(j + 1, n - 1)
            f = ((x[hi_] - x[lo_]) * (net.bx[sgm[0]] - net.ax[sgm[0]]) + (y[hi_] - y[lo_]) * (net.by[sgm[0]] - net.ay[sgm[0]])) >= 0
            way_stop[(net.way_ids[net.way_of_seg[sgm[0]]], 0 if f else 1)] += 1
            if ndist[0] <= a.node_radius:
                if int(nid[0]) in stopped_here:
                    capped += 1; continue
                stopped_here.add(int(nid[0]))
                node_stop[int(nid[0])] += 1; node_dur[int(nid[0])] += e["dur"]
    return {"node_pass": node_pass, "node_stop": node_stop, "node_dur": node_dur, "way_km": way_km, "way_stop": way_stop,
                "way_pass": way_pass, "kinds": kinds, "kind_dur": kind_dur, "pts_total": pts_total, "pts_snapped": pts_snapped,
                "ev_total": ev_total, "ev_snapped": ev_snapped, "km": km, "capped": capped}


def what_is_there(net, nid, near_tree):
    tg = net.node_tag.get(nid, {})
    lab = [f"{k}={v}" for k, v in tg.items() if k in ("highway", "crossing") and (k == "crossing" or v in snap.NODE_HW)]
    if lab:
        return "tagged node: " + ", ".join(lab)
    nx, ny = net.node_xy[nid]
    near = near_tree(nx, ny)
    if near:
        return f"{near[0]} {near[1]:.0f} m away"
    hws = sorted({net.ways[net.way_ids[w]][0] for w in net.node_ways.get(nid, ())})
    if len(hws) >= 2 and net.node_deg.get(nid, 0) >= 3:
        return "junction " + " x ".join(hws[:3])
    if net.node_deg.get(nid, 0) >= 3:
        return f"junction of {hws[0]} ways" if hws else "junction"
    return "nothing tagged (mid-way / bend)"


def prep_net_labels(net):
    from collections import defaultdict as dd
    nw, deg = dd(set), Counter()
    for k in range(len(net.na)):
        w = net.way_of_seg[k]
        nw[int(net.na[k])].add(int(w)); nw[int(net.nb[k])].add(int(w))
        deg[int(net.na[k])] += 1; deg[int(net.nb[k])] += 1
    net.node_ways, net.node_deg = nw, deg
    tagged = [(nid, net.node_xy[nid]) for nid, tg in net.node_tag.items()
              if nid in net.node_xy and (tg.get("highway") in snap.NODE_HW or "crossing" in tg)]
    from shapely import STRtree, points
    if not tagged:
        return lambda x, y: None
    tr = STRtree(points([p[1][0] for p in tagged], [p[1][1] for p in tagged]))
    def near(x, y):
        from shapely.geometry import Point
        j = tr.query_nearest(Point(x, y), max_distance=25, all_matches=False)
        if len(j) == 0:
            return None
        nid = tagged[int(j[0])][0]
        tg = net.node_tag[nid]
        lab = tg.get("highway") if tg.get("highway") in snap.NODE_HW else f"crossing={tg.get('crossing', 'yes')}"
        d = math.hypot(x - tagged[int(j[0])][1][0], y - tagged[int(j[0])][1][1])
        return (lab, d)
    return near


def write_nodes(path, net, st, a):
    rows = []
    for nid, p in st["node_pass"].items():
        s_ = st["node_stop"].get(nid, 0)
        lon, lat = net.node_ll[nid]
        rows.append((nid, round(lat, 6), round(lon, 6), p, s_, round(s_ / p, 3),
                     round(st["node_dur"].get(nid, 0) / s_, 1) if s_ else ""))
    thr = 1
    while True:
        sel = [r for r in rows if r[3] >= thr]
        size = sum(len(",".join(map(str, r))) + 1 for r in sel) + 60
        if size < 900_000 or thr > 50:
            break
        thr += 1
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["node_id", "lat", "lon", "passes", "stops", "probability", "mean_stop_s"])
        w.writerows(sorted(sel, key=lambda r: (-r[4], -r[3])))
    return thr, len(rows), len(sel)


def write_ways(path, net, st):
    keys = set(st["way_km"]) | set(st["way_stop"])
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["way_id", "highway", "direction", "km_ridden", "ride_passes", "stops", "stops_per_km"])
        for k in sorted(keys, key=lambda k: (-st["way_stop"].get(k, 0), k)):
            km = st["way_km"].get(k, 0)
            if km < 0.05 and not st["way_stop"].get(k):
                continue
            wid, di = k
            w.writerow([wid, net.ways[wid][0], "fwd" if di == 0 else "bwd", round(km, 3), st["way_pass"].get(k, 0),
                        st["way_stop"].get(k, 0), round(st["way_stop"].get(k, 0) / km, 2) if km > 0.05 else ""])


def md_table(h, rows):
    return "\n".join(["| " + " | ".join(h) + " |", "|" + "---|" * len(h)] + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def report(label, net, st, a, near, extra_lines):
    L = [f"### {label}", ""] + extra_lines
    k = st["kinds"]
    L += ["", md_table(["stop kind", "events", "total stopped time (h)", "mean (s)"],
                       [[kk, k[kk], f"{st['kind_dur'][kk] / 3600:.2f}", f"{st['kind_dur'][kk] / k[kk]:.0f}" if k[kk] else "-"] for kk in ("pause", "gap", "slow", "rest")]
                       + [["**all**", sum(k.values()), f"{sum(st['kind_dur'].values()) / 3600:.2f}",
                           f"{sum(st['kind_dur'].values()) / max(st['ev_total'], 1):.0f}"]])]
    np5 = [n for n, p in st["node_pass"].items() if p >= 5]
    nstop5 = [n for n in np5 if st["node_stop"].get(n)]
    L += ["", md_table(["metric", "value"], [
        ["km ridden (haversine)", f"{st['km']:.0f}"],
        [f"trackpoint snap rate (<= {a.snap_m:g} m)", f"{100 * st['pts_snapped'] / max(st['pts_total'], 1):.1f} % of {st['pts_total']}"],
        ["stop-event snap rate (excl. rest)", f"{100 * st['ev_snapped'] / max(st['ev_total'], 1):.1f} % of {st['ev_total']}"],
        ["distinct nodes with >= 1 pass", len(st["node_pass"])],
        ["nodes with >= 5 passes", len(np5)],
        ["... of which with >= 1 stop", len(nstop5)],
        ["nodes with >= 5 passes that are junctions (>= 3 segments) or tagged signals/stop/give_way/crossing", sum(1 for n in np5 if net.node_deg.get(n, 0) >= 3 or net.node_tag.get(n, {}).get("highway") in snap.NODE_HW or "crossing" in net.node_tag.get(n, {}))],
        ["nodes with >= 10 passes", sum(1 for p in st["node_pass"].values() if p >= 10)],
        [f"stop events attached to a node (<= {a.node_radius:g} m)", sum(st["node_stop"].values())],
        ["extra same-ride same-node stops dropped by the one-stop-per-ride-per-node cap", st["capped"]],
    ])]
    top = sorted(np5, key=lambda n: (-st["node_stop"].get(n, 0), -st["node_pass"][n]))[:20]
    rows = []
    for n in top:
        lon, lat = net.node_ll[n]
        s_ = st["node_stop"].get(n, 0)
        rows.append([n, f"{lat:.5f},{lon:.5f}", st["node_pass"][n], s_, f"{s_ / st['node_pass'][n]:.2f}",
                     f"{st['node_dur'].get(n, 0) / s_:.0f}" if s_ else "-", what_is_there(net, n, near)])
    L += ["", "Top 20 nodes by stop count (>= 5 passes):", "",
          md_table(["node", "lat,lon", "passes", "stops", "p(stop)", "mean stop s", "what is there (OSM)"], rows)]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["eric", "osm"])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--speed-thr", type=float, default=1.0)
    ap.add_argument("--min-stop-s", type=float, default=3.0)
    ap.add_argument("--merge-s", type=float, default=10.0)
    ap.add_argument("--end-margin-m", type=float, default=200.0)
    ap.add_argument("--gap-s", type=float, default=2.0)
    ap.add_argument("--data-gap-s", type=float, default=30.0)
    ap.add_argument("--gap-max-disp", type=float, default=100.0)
    ap.add_argument("--run-max-dt", type=float, default=None, help="max dt inside a slow run (default 5 s eric, 20 s osm)")
    ap.add_argument("--max-stop-s", type=float, default=300.0, help="longer events are kind 'rest' (excluded from node stats)")
    ap.add_argument("--snap-m", type=float, default=20.0)
    ap.add_argument("--node-radius", type=float, default=30.0, help="max point/stop->node distance for a pass/stop at a node")
    ap.add_argument("--max-median-speed", type=float, default=12.0)
    ap.add_argument("--min-median-speed", type=float, default=0.0, help="OSM: also exclude traces slower than this (walkers); default off")
    ap.add_argument("--tag", default="", help="suffix for output file names")
    ap.add_argument("--max-bigroad-frac", type=float, default=0.5, help="exclude OSM traces with more than this share of snapped points on motorway/trunk")
    ap.add_argument("--extract", "--pbf", dest="pbf", default=str(ROOT / "data/osm/ireland.osm.pbf"),
                    help="OSM extract (default Ireland); the network cache is keyed by its path")
    ap.add_argument("--region", default="", help="tag used in output file names, e.g. berlin (default: none = Ireland)")
    ap.add_argument("--extract-bbox", default=None, help="lon0,lat0,lon1,lat1 of rides counted as inside the extract (default: Ireland, or Brandenburg for --region berlin)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.source:
        ap.error("--source required")
    if a.run_max_dt is None:
        a.run_max_dt = 5.0 if a.source == "eric" else 20.0
    t_start = time.time()
    if a.extract_bbox:
        a.inbox = tuple(float(v) for v in a.extract_bbox.split(","))
    else:
        a.inbox = (11.2, 51.3, 14.8, 53.6) if a.region == "berlin" else IRELAND
    if a.region:
        a.tag = f"{a.tag}_{a.region}"
    extra = []
    if a.source == "eric":
        keep, dropped = load_eric(a)
        ire = [r for r in keep if not r.get("outside")]
        outs = [r for r in keep if r.get("outside")]
        extra += [f"Files {len(keep) + len(dropped)}; used {len(ire)} inside the extract bbox; dropped {len(dropped)}: "
                  + "; ".join(f"{i} ({r})" for i, r in dropped)]
        extra += [f"Outside the extract (stop events counted, not snapped): {len(outs)} rides, {sum(track_km(r['s']) for r in outs):.0f} km"]
        bc = defaultdict(lambda: [0, 0.0])
        for r in outs:
            c = country_of(r["s"].lat[0], r["s"].lon[0]); bc[c][0] += 1; bc[c][1] += track_km(r["s"])
        extra += ["Unsnapped (outside extract) by country: " + "; ".join(f"{c}: {n} rides, {k:.0f} km" for c, (n, k) in sorted(bc.items()))]
        items = [(r["id"], r["s"]) for r in ire]
        allitems = [(r["id"], r["s"]) for r in keep]
    else:
        tr, meta = load_osm(a)
        extra += [f"Pages loaded: {len(glob.glob(str(ROOT / 'data/gps/osm_trackpoints_p*.gpx')))}; trackpoints {meta['total_pts']}, with <time> {meta['ts_pts']} ({100 * meta['ts_pts'] / max(meta['total_pts'], 1):.1f} %); trkseg {meta['total_seg']}, with time {meta['ts_seg']} ({100 * meta['ts_seg'] / max(meta['total_seg'], 1):.1f} %); distinct timestamped traces (merged across pages by URL, >= 5 pts) {meta['n_traces_ts']}"]
        items = [(u, s) for u, s in tr]
        allitems = items
    if a.source == "eric":
        pl = np.concatenate([s.lon for _, s in items]), np.concatenate([s.lat for _, s in items])
        print(f"loading network around {len(pl[0])} points", flush=True)
        net = snap.load_network(a.pbf, points=pl)
    else:
        net = snap.load_network(a.pbf, boxes=[(-6.52, 52.98, -6.08, 53.32)])
    near = prep_net_labels(net)
    print(f"network: {len(net.na)} segments, {len(net.way_ids)} ways; {time.time() - t_start:.0f}s", flush=True)
    rows, info = analyze(items, net, a, a.source)
    if a.source == "osm":
        n0 = len(rows)
        good, bad_speed, bad_big, bad_walk, bad_slow = [], 0, 0, 0, 0
        for r in rows:
            s = r[1]
            sp = speeds(s)
            med = float(np.median(sp))
            if med > a.max_median_speed:
                bad_speed += 1; continue
            if r[7] > a.max_bigroad_frac:
                bad_big += 1; continue
            if med < a.min_median_speed:
                bad_slow += 1; continue
            bad_walk += med < 2.5
            good.append(r)
        pts_all = sum(len(r[1].t) for r in rows); pts_good = sum(len(r[1].t) for r in good)
        km_all = sum(track_km(r[1]) for r in rows)
        extra += [(f"Traces analysed {n0}; excluded: median speed > {a.max_median_speed} m/s: {bad_speed}; > {100 * a.max_bigroad_frac:.0f} % of snapped points on motorway/trunk: {bad_big} "
                  f"; median speed < {a.min_median_speed} m/s (walking pace, only if flag set): {bad_slow} -> excluded share {100 * (bad_speed + bad_big + bad_slow) / max(n0, 1):.1f} % of traces; trackpoint share {100 * (pts_all - pts_good) / max(pts_all, 1):.1f} %; km before exclusion {km_all:.0f}"),
                  f"Kept traces with median speed < 2.5 m/s (walking pace, not excluded): {bad_walk}"]
        rows = good
        extra += [f"Trace length: median {np.median([len(r[1].t) for r in rows]):.0f} points, median sample interval {np.median([median_dt(r[1]) for r in rows]):.1f} s"]
    st = accumulate(rows, net, a)
    extra += [f"Traces/rides in node statistics: {len(rows)}; data-gap counters: " + ", ".join(f"{k}={v}" for k, v in sorted(info.items()))]
    if a.source == "eric":
        # event counts for outside-Ireland rides (not snapped)
        o = Counter()
        for _, s in [x for x in allitems if x not in items]:
            ev, _ = detect(s, a.speed_thr, a.min_stop_s, a.merge_s, a.end_margin_m, a.gap_s, a.data_gap_s, a.gap_max_disp, a.run_max_dt, max_stop_s=a.max_stop_s)
            o.update(e["kind"] for e in ev)
        extra += ["Stop events on rides outside the extract: " + (", ".join(f"{k}={v}" for k, v in sorted(o.items())) or "none")]
    out = ROOT / "data/samples" / f"observed_stops_{a.source}{a.tag}.csv"
    thr, nall, nsel = write_nodes(out, net, st, a)
    extra += [f"CSV {out.name}: {nsel} of {nall} nodes written (min passes {thr}); size {out.stat().st_size} bytes"]
    if a.source == "eric":
        write_ways(ROOT / "data/samples" / f"observed_ways_eric{a.tag}.csv", net, st)
    text = report(f"Source {'A (Eric)' if a.source == 'eric' else 'B (OSM public traces)'}", net, st, a, near, extra)
    (ROOT / "data/samples" / f"empirical_stops_{a.source}{a.tag}.md").write_text(text + "\n")
    print(text)
    print(f"\nruntime {time.time() - t_start:.0f}s")


if __name__ == "__main__":
    main()
