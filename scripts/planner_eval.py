"""Evaluate the flow planner against plain fastbike on fixed OD pairs.
Run (BRouter must be up: `make brouter`):
  uv run scripts/planner_eval.py [--pairs data/samples/planner_od_pairs.csv]
      [--out data/samples/planner_eval.csv] [--weights prior] [--n 4]
fastbike_* is the fastbike alt-0 candidate taken from the KEPT list (dedupe keeps the
first of any duplicate group and fastbike alt 0 is first in job order, so it is always kept).
delta_*_pct = (top - fastbike) / fastbike * 100; negative stops delta = fewer stops."""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flowplan import stop_model
from flowplan.brouter import DEFAULT_URL, BRouterClient
from flowplan.candidates import generate
from flowplan.ranking import ScoredCandidate, rank
from flowplan.scoring import FlowIndex, score

ROOT = Path(__file__).resolve().parent.parent
COLUMNS = ["name", "fastbike_km", "fastbike_stops", "fastbike_stops_per_km", "top_variant",
           "top_alt", "top_km", "top_stops", "top_stops_per_km", "delta_stops_pct",
           "delta_km_pct", "candidates_total", "candidates_kept", "skipped", "wall_s",
           "top_is_fastbike", "error"]


def _pct(new: float, ref: float) -> float:
    return (new - ref) / ref * 100 if ref else 0.0


def build_row(name: str, scored: list[ScoredCandidate], top: list[ScoredCandidate],
              total: int, skipped: int, wall_s: float) -> dict:
    """One output row from scored kept candidates and the ranked list (top[0] is best)."""
    row = dict.fromkeys(COLUMNS, "")
    row.update(name=name, candidates_total=total, candidates_kept=len(scored),
               skipped=skipped, wall_s=round(wall_s, 2))
    ref = next((s for s in scored if s.cand.variant == "fastbike" and s.cand.alt == 0), None)
    if ref is None or not top:
        row["error"] = "no fastbike alt0 candidate" if top else "no route"
        return row
    t = top[0]

    def spk(s):
        return s.score.expected_stops / (s.length_m / 1000) if s.length_m else 0.0

    row.update(fastbike_km=round(ref.length_m / 1000, 2),
               fastbike_stops=round(ref.expected_stops, 2),
               fastbike_stops_per_km=round(spk(ref), 3),
               top_variant=t.cand.variant, top_alt=t.cand.alt,
               top_km=round(t.length_m / 1000, 2), top_stops=round(t.expected_stops, 2),
               top_stops_per_km=round(spk(t), 3),
               delta_stops_pct=round(_pct(t.expected_stops, ref.expected_stops), 1),
               delta_km_pct=round(_pct(t.length_m, ref.length_m), 1),
               top_is_fastbike=t is ref)
    return row


def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("error")]
    ds = [float(r["delta_stops_pct"]) for r in ok]
    dk = [float(r["delta_km_pct"]) for r in ok]
    return {"pairs": len(rows), "ok": len(ok), "errors": len(rows) - len(ok),
            "mean_delta_stops_pct": round(statistics.mean(ds), 1) if ds else None,
            "median_delta_stops_pct": round(statistics.median(ds), 1) if ds else None,
            "mean_delta_km_pct": round(statistics.mean(dk), 1) if dk else None,
            "top_is_fastbike": sum(1 for r in ok if r["top_is_fastbike"] in (True, "True"))}


def markdown(rows: list[dict]) -> str:
    cols = [c for c in COLUMNS if c != "error"]
    if any(r.get("error") for r in rows):
        cols.append("error")
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=str(ROOT / "data/samples/planner_od_pairs.csv"))
    ap.add_argument("--out", default=str(ROOT / "data/samples/planner_eval.csv"))
    ap.add_argument("--weights", default="prior")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--workers", type=int, default=2,
                    help="client threads; run_brouter.sh serves with 2 server threads and "
                         "more concurrent requests get killed by its watchdog")
    ap.add_argument("--brouter", default=DEFAULT_URL)
    ap.add_argument("--region", default="ireland")
    a = ap.parse_args()
    model = stop_model.load(weights=a.weights)
    index = FlowIndex.load(a.region)
    client = BRouterClient(a.brouter)
    rows = []
    with open(a.pairs, newline="") as f:
        pairs = list(csv.DictReader(f))
    for p in pairs:
        t0 = time.perf_counter()
        try:
            start = (float(p["from_lon"]), float(p["from_lat"]))
            end = (float(p["to_lon"]), float(p["to_lat"]))
            kept, dropped, skipped = generate(client, start, end, region=a.region,
                                           max_workers=a.workers)
            scored = [ScoredCandidate(c, score(c.geometry, model, index)) for c in kept]
            top = rank(scored, n=a.n)
            row = build_row(p["name"], scored, top, len(kept) + len(dropped), len(skipped),
                            time.perf_counter() - t0)
        except Exception as e:  # noqa: BLE001 - record and continue
            row = dict.fromkeys(COLUMNS, "")
            row.update(name=p["name"], error=f"{type(e).__name__}: {e}",
                       wall_s=round(time.perf_counter() - t0, 2))
        rows.append(row)
        print(f"{row['name']}: {row['error'] or 'ok'} ({row['wall_s']}s)", file=sys.stderr)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"weights={model.weight_set}\n")
    print(markdown(rows))
    print("\n" + str(summarize(rows)))
    errs = [r for r in rows if r["error"]]
    if errs:
        print(f"\n{len(errs)} pair(s) errored: " + "; ".join(f"{r['name']}: {r['error']}" for r in errs))


if __name__ == "__main__":
    main()
