"""plan_eval row-building and summary helpers on synthetic data (no BRouter)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import plan_eval

SCN = {"name": "x", "mode": "loop", "from_lat": "53.3", "from_lon": "-6.28", "to_lat": "", "to_lon": "",
       "min_km": "40", "max_km": "50", "objective": "climb", "return": "same"}


def resp(km):
    return {"candidates_total": 9, "candidates_deduped": 5,
            "plan": {"calls": 30, "notes": ["a", "b"]},
            "routes": [{"id": "flow@90.0/alt0", "variant": "flow", "plan": {"heading_deg": 90.0},
                        "stats": {"distance_km": km, "ascent_m": 512.4, "climb_score": 80.2,
                                  "hardest_climb": {"length_m": 2000, "gain_m": 120, "avg_grade_pct": 6.0},
                                  "expected_stops": 3.456, "turns": 20, "longest_straight_km": 4.44,
                                  "cycle_km": {"path": 1.0, "lane": 2.0, "track": 0.5, "total_km": km}}}]}


def test_row_hit_and_miss():
    r = plan_eval.build_row(SCN, resp(45.0), 12.34)
    assert r["length_hit"] == "yes" and r["cycle_km"] == 3.5 and r["top_heading"] == "90"
    assert r["hardest_climb"] == "2.0km/120m/6.0%" and r["notes"] == "a; b" and r["in_range"] == 5
    assert plan_eval.build_row(SCN, resp(52.0), 1)["length_hit"] == "no"


def test_row_error_and_oneway():
    r = plan_eval.build_row(SCN, None, 1.0, "404: nope")
    assert r["error"] == "404: nope" and r["top_id"] == ""
    ow = dict(SCN, mode="one_way", min_km="", max_km="")
    assert plan_eval.build_row(ow, resp(30), 1)["length_hit"] == "n/a"


def test_summary_and_query():
    rows = [plan_eval.build_row(SCN, resp(45), 10), plan_eval.build_row(SCN, resp(60), 20),
            plan_eval.build_row(dict(SCN, mode="one_way", min_km="", max_km=""), resp(30), 6)]
    s = plan_eval.summarize(rows)
    assert s["length_hit"] == 1 and s["length_judged"] == 2 and s["length_hit_rate"] == 0.5
    assert s["mean_wall_s"] == {"loop": 15.0, "one_way": 6.0}
    qp = plan_eval.query_params(SCN, 4, 8, 48)
    assert qp["min_km"] == "40" and "to" not in qp and qp["from"] == "53.3,-6.28"
