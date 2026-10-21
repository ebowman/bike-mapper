#!/usr/bin/env python3
"""Score GPX routes for expected stops.

Usage: uv run scripts/flow_score.py ROUTE.gpx [...] [--region ireland]
                                     [--weights combined|ireland|prior]
"""
import argparse
import sys
from pathlib import Path

import gpxpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flowplan import scoring, stop_model


def read_points(path):
    with open(path) as f:
        g = gpxpy.parse(f)
    return [(p.longitude, p.latitude) for t in g.tracks for s in t.segments for p in s.points]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gpx", nargs="+")
    ap.add_argument("--region", default="ireland")
    ap.add_argument("--weights", default=None, choices=["combined", "ireland", "prior"])
    a = ap.parse_args()
    model = stop_model.load(weights=a.weights)
    index = scoring.FlowIndex.load(a.region)
    print(f"# weights={model.weight_set} index load {index.load_seconds:.1f}s", file=sys.stderr)
    hdr = ["file", "distance_km", "expected_stops", "stops_per_km", "expected_stop_s"] + list(scoring.CAUSES)
    print("| " + " | ".join(hdr) + " |\n|" + "---|" * len(hdr))
    for p in a.gpx:
        r = scoring.score(read_points(p), model, index)
        row = [Path(p).name, f"{r.distance_km:.2f}", f"{r.expected_stops:.2f}",
               f"{r.stops_per_km:.2f}", f"{r.expected_stop_s:.0f}"]
        row += [str(r.by_class[c]["events"]) for c in scoring.CAUSES]
        print("| " + " | ".join(row) + " |")


if __name__ == "__main__":
    main()
