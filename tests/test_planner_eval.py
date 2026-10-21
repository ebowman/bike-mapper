import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from flowplan.brouter import Candidate
from flowplan.ranking import ScoredCandidate, rank
from flowplan.scoring import RouteScore
from planner_eval import build_row, markdown, summarize


def sc(variant, alt, length_m, stops):
    c = Candidate(variant, variant, alt, [], length_m, 0, 0, 0)
    return ScoredCandidate(c, RouteScore(expected_stops=stops))


def row_for(name, items):
    return build_row(name, items, rank(items, n=4), len(items) + 2, 1, 1.234)


def test_row_better_than_fastbike():
    items = [sc("fastbike", 0, 10000, 10), sc("flow", 1, 11000, 5), sc("flow_hi", 0, 10500, 7)]
    r = row_for("a", items)
    assert r["top_variant"] == "flow" and r["top_alt"] == 1
    assert r["delta_stops_pct"] == -50.0 and r["delta_km_pct"] == 10.0
    assert r["fastbike_stops_per_km"] == 1.0 and r["top_stops_per_km"] == 0.455
    assert r["top_is_fastbike"] is False and r["candidates_total"] == 5 and r["skipped"] == 1


def test_row_fastbike_is_top():
    items = [sc("fastbike", 0, 10000, 3), sc("flow", 0, 10500, 5), sc("flow_hi", 0, 10800, 6)]
    r = row_for("b", items)
    assert r["top_is_fastbike"] is True and r["delta_stops_pct"] == 0.0


def test_row_without_fastbike_or_routes_is_error():
    assert row_for("c", [sc("flow", 0, 1000, 1)])["error"]
    assert build_row("d", [], [], 0, 16, 0.1)["error"] == "no route"


def test_summary_and_markdown():
    a = row_for("a", [sc("fastbike", 0, 10000, 10), sc("flow", 1, 11000, 5)])
    b = row_for("b", [sc("fastbike", 0, 10000, 3), sc("flow", 0, 10500, 5)])
    bad = build_row("e", [], [], 0, 16, 0.1)
    s = summarize([a, b, bad])
    assert s["pairs"] == 3 and s["ok"] == 2 and s["errors"] == 1
    assert s["mean_delta_stops_pct"] == -25.0 and s["median_delta_stops_pct"] == -25.0
    assert s["mean_delta_km_pct"] == 5.0 and s["top_is_fastbike"] == 1
    assert markdown([a, b, bad]).count("\n") == 4
