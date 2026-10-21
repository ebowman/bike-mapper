#!/usr/bin/env python3
"""Compile directional stop events into a self-contained per-region index (no PBF needed at request time).

Usage:
  uv run scripts/build_flow_index.py --region ireland [--pbf P] [--events E] [--out O]

Defaults: pbf data/osm/<region>.osm.pbf, events data/osm/events_<region>.csv, out data/flow/<region>.index.csv.

Input events (dhy.10): way_id,dir,vertex_idx,node_id,cause,amount = "arriving on way_id in direction dir at vertex
vertex_idx (= node_id)".

Output schema (CSV, coordinates with 7 decimals):
  node_id,lat,lon,from_node_id,from_lat,from_lon,way_id,dir,cause,amount
where (from_*) is the vertex the rider arrives FROM (fwd: vertex_idx-1, bwd: vertex_idx+1). from_* are empty when
there is no such vertex (event at the way's first vertex fwd / last vertex bwd); the scorer matches those by node only.
Events whose way is gone from the PBF or whose node is not on the way are dropped. Exit status is non-zero if
fewer than 95% of events are retained.
"""
import argparse
import csv
import os
import sys
from collections import Counter

import osmium


def build_row(nodes, event):
    """nodes: [(node_id, lat, lon), ...] of the way; event: dict with way_id,dir,vertex_idx,node_id,cause,amount.

    Returns (row_dict_or_None, status) with status in {"ok", "no_from_vertex", "dropped_missing_vertex"}.
    """
    nid = int(event["node_id"])
    idx = int(event["vertex_idx"])
    if not (0 <= idx < len(nodes) and nodes[idx][0] == nid):
        idx = next((i for i, n in enumerate(nodes) if n[0] == nid), None)
        if idx is None:
            return None, "dropped_missing_vertex"
    fidx = idx - 1 if event["dir"] == "fwd" else idx + 1
    _, lat, lon = nodes[idx]
    row = {"node_id": nid, "lat": f"{lat:.7f}", "lon": f"{lon:.7f}",
           "from_node_id": "", "from_lat": "", "from_lon": "",
           "way_id": event["way_id"], "dir": event["dir"], "cause": event["cause"], "amount": event["amount"]}
    if 0 <= fidx < len(nodes):
        fn, flat, flon = nodes[fidx]
        row.update(from_node_id=fn, from_lat=f"{flat:.7f}", from_lon=f"{flon:.7f}")
        return row, "ok"
    return row, "no_from_vertex"


FIELDS = ["node_id", "lat", "lon", "from_node_id", "from_lat", "from_lon", "way_id", "dir", "cause", "amount"]


def load_way_nodes(pbf, needed):
    out = {}
    fp = (osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations()
          .with_filter(osmium.filter.KeyFilter("highway")))
    for w in fp:
        if not w.is_way() or w.id not in needed:
            continue
        out[w.id] = [(n.ref, n.lat, n.lon) for n in w.nodes if n.location.valid()]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="ireland")
    ap.add_argument("--pbf")
    ap.add_argument("--events")
    ap.add_argument("--out")
    a = ap.parse_args()
    pbf = a.pbf or f"data/osm/{a.region}.osm.pbf"
    events_path = a.events or f"data/osm/events_{a.region}.csv"
    out_path = a.out or f"data/flow/{a.region}.index.csv"

    with open(events_path, newline="") as f:
        events = [r for r in csv.DictReader(f) if r.get("way_id") and r["way_id"] != "way_id"]
    needed = {int(e["way_id"]) for e in events}
    print(f"events in: {len(events)}; ways needed: {len(needed)}; reading {pbf} ...", file=sys.stderr)
    ways = load_way_nodes(pbf, needed)

    counts, causes, rows = Counter(), Counter(), 0
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS)
        wr.writeheader()
        for e in events:
            nodes = ways.get(int(e["way_id"]))
            if nodes is None:
                counts["dropped_missing_way"] += 1
                counts["dropped_missing_vertex"] += 1
                continue
            row, status = build_row(nodes, e)
            counts[status] += 1
            if row is None:
                continue
            wr.writerow(row)
            rows += 1
            causes[row["cause"]] += 1
    print(f"events in={len(events)} rows out={rows} dropped_missing_vertex={counts['dropped_missing_vertex']} "
          f"(of which way missing from PBF={counts['dropped_missing_way']}) no_from_vertex={counts['no_from_vertex']}",
          file=sys.stderr)
    print("per-cause: " + " ".join(f"{k}={v}" for k, v in sorted(causes.items())), file=sys.stderr)
    if rows < 0.95 * len(events):
        print("ERROR: fewer than 95% of events retained", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
