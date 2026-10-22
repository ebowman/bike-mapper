"""Evaluate the planning modes (loop / out-and-back / one-way) on fixed scenarios.
Run (BRouter must be up: `make brouter`):
  uv run scripts/plan_eval.py [--scenarios data/samples/plan_eval_scenarios.csv]
      [--out data/samples/plan_eval.csv] [--n 4] [--bearings 8] [--max-calls 48]
Scenarios run sequentially through PlannerService.plan with default settings (the same code as /api/plan
and the MCP); a failing scenario writes its error in the row and the run continues.
length_hit = top route inside [min_km, max_km] (one-way: n/a). in_range = candidates kept after dedupe."""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
COLUMNS = ["name", "mode", "objective", "return", "min_km", "max_km", "candidates_total", "in_range", "calls",
           "wall_s", "top_id", "top_variant", "top_heading", "top_km", "ascent_m", "climb_score",
           "hardest_climb", "expected_stops", "turns", "longest_straight_km", "cycle_km", "length_hit",
           "notes", "error"]


def _num(v):
    return None if v in (None, "") else float(v)


def query_params(scn: dict, n: int, bearings: int, max_calls: int) -> dict:
    """/api/plan query mapping for one scenario row."""
    qp = {"mode": scn["mode"], "from": f"{scn['from_lat']},{scn['from_lon']}", "objective": scn["objective"],
          "return": scn["return"], "n": str(n), "bearings": str(bearings), "max_calls": str(max_calls)}
    if scn.get("to_lat"):
        qp["to"] = f"{scn['to_lat']},{scn['to_lon']}"
    if scn.get("min_km"):
        qp["min_km"], qp["max_km"] = str(scn["min_km"]), str(scn["max_km"])
    return qp


def climb_str(c) -> str:
    return "-" if not c else f"{c['length_m'] / 1000:.1f}km/{c['gain_m']:.0f}m/{c['avg_grade_pct']:.1f}%"


def build_row(scn: dict, resp: dict | None, wall_s: float, error: str = "") -> dict:
    """One output row from a scenario and the plan response (None on error)."""
    row = dict.fromkeys(COLUMNS, "")
    row.update(name=scn["name"], mode=scn["mode"], objective=scn["objective"], **{"return": scn["return"]},
               min_km=scn.get("min_km", ""), max_km=scn.get("max_km", ""), wall_s=round(wall_s, 1),
               error=error)
    if resp is None:
        row["length_hit"] = "n/a" if scn["mode"] == "one_way" else ""
        return row
    routes = resp.get("routes") or []
    row.update(candidates_total=resp.get("candidates_total", ""), in_range=resp.get("candidates_deduped", ""),
               calls=(resp.get("plan") or {}).get("calls", ""),
               notes="; ".join((resp.get("plan") or {}).get("notes") or []))
    if not routes:
        row["error"] = row["error"] or "no routes"
        row["length_hit"] = "n/a" if scn["mode"] == "one_way" else "no"
        return row
    r = routes[0]
    s, p = r["stats"], r.get("plan") or {}
    ck = s["cycle_km"]
    km = s["distance_km"]
    row.update(top_id=r["id"], top_variant=r["variant"],
               top_heading="" if p.get("heading_deg") is None else f"{p['heading_deg']:g}",
               top_km=round(km, 1),
               ascent_m="" if s["ascent_m"] is None else round(s["ascent_m"]),
               climb_score=round(s["climb_score"]), hardest_climb=climb_str(s["hardest_climb"]),
               expected_stops=round(s["expected_stops"], 2), turns=s["turns"],
               longest_straight_km=round(s["longest_straight_km"], 1),
               cycle_km=round(ck["path"] + ck["lane"] + ck["track"], 1))
    lo, hi = _num(scn.get("min_km")), _num(scn.get("max_km"))
    if scn["mode"] == "one_way" or lo is None:
        row["length_hit"] = "n/a"
    else:
        row["length_hit"] = "yes" if lo <= km <= hi else "no"
    return row


def summarize(rows: list[dict]) -> dict:
    """length-hit rate (over rows with a yes/no) and mean wall time per mode."""
    judged = [r for r in rows if r["length_hit"] in ("yes", "no")]
    hits = sum(r["length_hit"] == "yes" for r in judged)
    by_mode: dict = {}
    for r in rows:
        by_mode.setdefault(r["mode"], []).append(float(r["wall_s"] or 0))
    return {"length_hit": hits, "length_judged": len(judged),
            "length_hit_rate": hits / len(judged) if judged else None,
            "mean_wall_s": {m: round(statistics.mean(v), 1) for m, v in by_mode.items()},
            "errors": sum(bool(r["error"]) for r in rows)}


MD_COLS = ["name", "candidates_total", "in_range", "calls", "wall_s", "top_id", "top_km", "ascent_m",
           "climb_score", "hardest_climb", "expected_stops", "turns", "longest_straight_km", "cycle_km",
           "length_hit"]


def markdown(rows: list[dict]) -> str:
    out = ["| " + " | ".join(MD_COLS) + " |", "|" + "---|" * len(MD_COLS)]
    for r in rows:
        cells = [str(r[c]) if r[c] != "" else "-" for c in MD_COLS]
        if r["error"]:
            cells[5] = "ERROR: " + r["error"][:60].replace("|", "/")
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenarios", default=str(ROOT / "data/samples/plan_eval_scenarios.csv"))
    ap.add_argument("--out", default=str(ROOT / "data/samples/plan_eval.csv"))
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--bearings", type=int, default=8)
    ap.add_argument("--max-calls", type=int, default=48)
    a = ap.parse_args(argv)

    from flow_mcp import build_service
    from flowplan.service import ServiceError
    svc = build_service()
    with open(a.scenarios, newline="") as f:
        scenarios = list(csv.DictReader(f))
    rows = []
    for scn in scenarios:
        t0 = time.perf_counter()
        resp, err = None, ""
        try:
            resp = svc.plan(query_params(scn, a.n, a.bearings, a.max_calls))
        except ServiceError as e:
            err = f"{e.status}: {e.detail}"
        except Exception as e:  # noqa: BLE001 - keep going, record the failure
            err = f"{type(e).__name__}: {e}"
        row = build_row(scn, resp, time.perf_counter() - t0, err)
        rows.append(row)
        print(f"{scn['name']}: {row['wall_s']}s {row['top_km'] or '-'} km {err}", file=sys.stderr, flush=True)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(markdown(rows))
    print("\n" + str(summarize(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
