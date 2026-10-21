#!/usr/bin/env python3
"""Open motor-traffic count points vs OSM road network: points per highway class + minor-road coverage.

Usage (from repo root):
  uv run python scripts/traffic_coverage.py ireland     # TII TMU counters (data/traffic/tii/) vs data/osm/ireland.osm.pbf
  uv run python scripts/traffic_coverage.py devon       # DfT count points (data/traffic/dft/, Devon+Plymouth+Torbay) vs data/osm/devon.osm.pbf
  uv run python scripts/traffic_coverage.py tags        # count aadt/traffic_volume-like tags in ireland.osm.pbf

Steps: load count points -> WGS84 -> assert inside country bbox -> snap to nearest OSM highway way <= 30 m with
scripts/snap.py (EPSG:2157 STRtree) -> table of points per highway class -> fraction of tertiary/unclassified km within
2 km of any count point (2 km discs in EPSG:2157, intersected with the way segments).
EPSG:2157 (ITM) is also used for the Devon run: distances there are scaled ~0.3-0.5 % off at 3.5W; irrelevant at this precision.
Limitation: dual carriageways may snap to the wrong carriageway; not corrected.
"""
import collections
import json
import pathlib
import sys

import numpy as np
import pandas as pd
import shapely

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from snap import load_network, project

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAP_M, BUF_M = 30.0, 2000.0
MINOR = ("tertiary", "unclassified")
ORDER = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
         "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link", "living_street", "service", "track", "path", "cycleway"]


def load_points(which):
    if which == "ireland":
        with open(ROOT / "data/traffic/tii/tmu-traffic-counters.geojson") as fh:
            d = json.load(fh)
        rows = [{"site": f["properties"]["field_2"], "name": f["properties"]["field_1"],
                 "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1],
                 "cat": f["properties"]["field_1"].split()[0][:1]} for f in d["features"]]
        df = pd.DataFrame(rows)
        bbox = (-10.8, 51.3, -5.3, 55.5)
        pbf = ROOT / "data/osm/ireland.osm.pbf"
    else:  # devon
        cp = pd.read_csv(ROOT / "data/traffic/dft/count_points.csv", low_memory=False)
        # count_points.csv: one row per point, year = last year with an AADF record -> keep points active in the last 10 y
        cp = cp[(cp.year >= cp.year.max() - 9) & cp.local_authority_name.isin(["Devon", "Plymouth", "Torbay"])]
        df = pd.DataFrame({"site": cp.count_point_id, "name": cp.road_name, "lon": cp.longitude, "lat": cp.latitude, "cat": cp.road_category})
        # which of them were physically counted (not estimated) in the last 10 years
        a = pd.read_csv(ROOT / "data/traffic/dft/dft_traffic_counts_aadf.csv", usecols=["count_point_id", "year", "estimation_method"])
        a = a[(a.estimation_method == "Counted") & (a.year >= a.year.max() - 9)]
        df["counted10y"] = df.site.isin(set(a.count_point_id))
        bbox = (-5.3, 50.1, -2.8, 51.3)
        pbf = ROOT / "data/osm/devon.osm.pbf"
    assert df.lon.between(bbox[0], bbox[2]).all() and df.lat.between(bbox[1], bbox[3]).all(), "points outside country bbox"
    return df.reset_index(drop=True), bbox, pbf


def md(df):
    return df.to_markdown(index=False) if hasattr(df, "to_markdown") else df.to_string(index=False)


def table(rows, headers):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def run(which):
    df, bbox, pbf = load_points(which)
    print(f"{which}: {len(df)} count points loaded")
    net = load_network(str(pbf), boxes=[bbox])
    x, y = project(df.lon.values, df.lat.values)
    seg, _, d = net.snap(x, y, max_m=SNAP_M)
    way_hw = np.array([net.ways[w][0] for w in net.way_ids])
    seg_hw = way_hw[net.way_of_seg]
    df["hw"] = np.where(seg >= 0, seg_hw[np.maximum(seg, 0)], "(no way within 30 m)")
    df["snap_m"] = d
    print(f"snapped {int((seg >= 0).sum())}/{len(df)}; median snap distance {np.median(d[seg >= 0]):.1f} m")

    # table 1: points per highway class
    flt = [("all points", np.ones(len(df), bool))]
    if which == "devon":
        flt.append(("counted (not estimated) in last 10 y", df.counted10y.values))
    ptab = []
    for lab, m in flt:
        c = collections.Counter(df.hw[m])
        ptab.append((lab, c))
    classes = [c for c in ORDER if any(c in p[1] for p in ptab)] + sorted({k for p in ptab for k in p[1]} - set(ORDER))
    t1 = table([[c] + [p[1].get(c, 0) for p in ptab] for c in classes] + [["TOTAL"] + [sum(p[1].values()) for p in ptab]],
               ["OSM highway class snapped to"] + [p[0] for p in ptab])

    # table 2: km of each class within 2 km of any count point
    ax, ay, bx, by = net.ax, net.ay, net.bx, net.by
    seglen = np.hypot(bx - ax, by - ay) / 1000.0
    variants = [("any count point", np.ones(len(df), bool))]
    if which == "ireland":
        variants.append(("count points on secondary or lower (not motorway/trunk/primary)", df.hw.isin(["secondary", "tertiary", "unclassified", "residential", "service"]).values))
    else:
        variants.append(("points counted (not estimated) in last 10 y", df.counted10y.values))
        variants.append(("counted-10y points on MCU (minor C/U) roads", (df.counted10y & (df.cat == "MCU")).values))
    t2rows = []
    for lab, m in variants:
        if not m.any():
            continue
        # distance test on <=100 m sub-piece midpoints (exact polygon clipping was >10 min on Ireland-size inputs)
        within = np.zeros(len(seglen))
        npc = np.maximum(1, np.ceil(seglen * 10).astype(int))   # 100 m pieces
        sid = np.repeat(np.arange(len(seglen)), npc)
        k = np.arange(len(sid)) - np.repeat(np.cumsum(npc) - npc, npc)
        f = (k + 0.5) / npc[sid]
        mx, my = ax[sid] + f * (bx - ax)[sid], ay[sid] + f * (by - ay)[sid]
        ii, _ = shapely.STRtree(shapely.points(x[m], y[m])).query_nearest(shapely.points(mx, my), max_distance=BUF_M, all_matches=False)
        hit = np.zeros(len(sid), bool); hit[ii] = True
        np.add.at(within, sid[hit], (seglen / npc)[sid[hit]])
        res = {}
        for cls, hws in [("tertiary", ["tertiary"]), ("unclassified", ["unclassified"]), ("tertiary+unclassified", list(MINOR)),
                         ("secondary", ["secondary"]), ("residential", ["residential"])]:
            k = np.isin(seg_hw, hws)
            res[cls] = (seglen[k].sum(), within[k].sum())
        for cls, (tot, w) in res.items():
            t2rows.append([lab, cls, f"{tot:,.0f}", f"{w:,.0f}", f"{100*w/tot:.1f}", f"{100-100*w/tot:.1f}"])
    t2 = table(t2rows, ["count-point set", "class", "total km", "km within 2 km", "% within", "% NOT within"])
    # sanity
    out = f"## {which}: count points per OSM highway class (snap <= {SNAP_M:.0f} m)\n\n{t1}\n\n"
    out += f"Snapped {int((seg>=0).sum())}/{len(df)}; median snap {np.median(d[seg>=0]):.1f} m.\n\n"
    out += f"## {which}: km of road within {BUF_M/1000:.0f} km of a count point\n\n{t2}\n"
    if which == "devon":
        out += "\nDfT cat x snapped class (all points):\n\n" + pd.crosstab(df.cat, df.hw).to_string() + "\n"
    print(out)
    (ROOT / f"data/samples/traffic_coverage_{which}.md").write_text(out)
    df.to_csv(ROOT / f"data/traffic/snapped_{which}.csv", index=False)


def tags():
    import osmium
    pbf = ROOT / "data/osm/ireland.osm.pbf"
    keys = ("traffic_volume", "aadt", "AADT", "traffic_count", "traffic:volume", "average_traffic", "traffic_flow")
    c = collections.Counter()
    fp = osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY).with_filter(osmium.filter.KeyFilter(*keys))
    for o in fp:
        for k in keys:
            if k in o.tags:
                c[(k, "way" if o.is_way() else "node")] += 1
    print("aadt-like tags in ireland.osm.pbf:", dict(c) or "none found")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("ireland", "devon", "tags"):
        sys.exit(__doc__)
    tags() if sys.argv[1] == "tags" else run(sys.argv[1])
