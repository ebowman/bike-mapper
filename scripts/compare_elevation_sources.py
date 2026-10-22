"""Compare total ascent / hardest climb from BRouter per-node elevations vs DEM samples on the plan_eval top routes.
Run (BRouter must be up): uv run scripts/compare_elevation_sources.py [--out data/samples/elevation_source_comparison.csv]
Re-plans the scenarios in data/samples/plan_eval_scenarios.csv in-process with elevation_source=brouter (the plan is
the same candidates either way; only the ranking input differs, so the top route is the BRouter-ranked one), then
for each top route computes ascent with hysteresis 3 m and 10 m from (a) BRouter elevations on the raw nodes,
(b) BRouter elevations resampled at 25 m, (c) DEM samples at the nodes, (d) DEM resampled at 25 m, plus the hardest
climb gain on each source."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent

COLUMNS = ["name", "top_id", "km", "dem_coverage", "brouter_asc_h3", "brouter_asc25_h3", "dem_asc_h3", "dem_asc25_h3",
           "brouter_asc_h10", "brouter_asc25_h10", "dem_asc_h10", "dem_asc25_h10", "ratio_dem_brouter_h3",
           "brouter_hardest_gain", "dem_hardest_gain"]


def _asc25(geometry, ele, hyst):
    import numpy as np
    from flowplan.climbs import STEP, elevation_stats, resample
    d, z = resample(geometry, ele)
    # the 25 m grid has no lon/lat; elevation_stats only needs distance, so feed a synthetic straight line
    coords = [(0.0, float(x) / 111_320.0) for x in d]
    return elevation_stats(coords, [float(v) for v in z], hyst)["ascent_m"], STEP, np


def compare_route(c, dem):
    from flowplan.climbs import climb_score, detect_climbs, elevation_stats
    from flowplan.terrain import dem_route_elevations
    dele, cov = dem_route_elevations(dem, c.geometry)
    row = {"dem_coverage": round(cov, 3)}
    for tag, ele in (("brouter", c.elevations), ("dem", dele)):
        if ele is None:
            continue
        for h in (3, 10):
            row[f"{tag}_asc_h{h}"] = round(elevation_stats(c.geometry, ele, h)["ascent_m"])
            row[f"{tag}_asc25_h{h}"] = round(_asc25(c.geometry, ele, h)[0])
        hc = climb_score(detect_climbs(c.geometry, ele))["hardest"]
        row[f"{tag}_hardest_gain"] = round(hc.gain_m) if hc else 0
    if row.get("brouter_asc_h3"):
        row["ratio_dem_brouter_h3"] = round(row["dem_asc25_h3"] / row["brouter_asc_h3"], 2)
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenarios", default=str(ROOT / "data/samples/plan_eval_scenarios.csv"))
    ap.add_argument("--out", default=str(ROOT / "data/samples/elevation_source_comparison.csv"))
    a = ap.parse_args(argv)
    from flow_mcp import build_service
    from plan_eval import query_params
    svc = build_service()
    rows = []
    with open(a.scenarios, newline="") as f:
        scenarios = list(csv.DictReader(f))
    for scn in scenarios:
        qp = query_params(scn, 4, 8, 72)
        qp["elevation_source"] = "brouter"
        _resp, top = svc.plan_scored(qp)
        c = top[0].cand
        row = dict.fromkeys(COLUMNS, "")
        row.update(name=scn["name"], top_id=c.route_id, km=round(c.length_m / 1000, 1), **compare_route(c, svc.dem))
        rows.append(row)
        print(row, file=sys.stderr, flush=True)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print("| " + " | ".join(COLUMNS) + " |\n|" + "---|" * len(COLUMNS))
    for r in rows:
        print("| " + " | ".join(str(r[c]) for c in COLUMNS) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
