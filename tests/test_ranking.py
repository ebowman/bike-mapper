from flowplan.brouter import Candidate
from flowplan.ranking import ScoredCandidate, rank
from flowplan.scoring import RouteScore


def sc(variant, alt, length_m, stops):
    c = Candidate(variant, variant, alt, [], length_m, 0, 0, 0)
    return ScoredCandidate(c, RouteScore(expected_stops=stops))


def test_guard_drops_long_candidate_when_enough_remain():
    items = [sc("fastbike", 0, 10000, 5), sc("a", 0, 10500, 4), sc("b", 0, 11000, 6),
             sc("c", 0, 12000, 7), sc("long", 0, 15000, 1)]
    out = rank(items, n=6)
    assert "long" not in [s.cand.variant for s in out]
    assert len(out) == 4


def test_guard_not_applied_when_too_few():
    items = [sc("fastbike", 0, 10000, 5), sc("long", 0, 15000, 1)]
    out = rank(items)
    assert [s.cand.variant for s in out] == ["long", "fastbike"]


def test_top_n_ordering_and_tie_break():
    items = [sc("fastbike", 0, 10000, 5), sc("a", 0, 10200, 3), sc("b", 0, 10100, 3),
             sc("c", 0, 10300, 4), sc("d", 0, 10400, 6)]
    out = rank(items, n=3)
    assert [s.cand.variant for s in out] == ["b", "a", "c"]
    assert [s.rank for s in out] == [1, 2, 3]


def test_delta_vs_fastest():
    items = [sc("fastbike", 0, 10000, 5), sc("a", 0, 10500, 3), sc("b", 0, 11000, 4)]
    out = rank(items)
    d = out[0].delta_vs_fastest
    assert d["stops"] == -2 and abs(d["km"] - 0.5) < 1e-9
    assert out[-1].delta_vs_fastest == {"stops": 0, "km": 0, "turns": 0}


def test_no_fastest_gives_none():
    out = rank([sc("a", 0, 1000, 1)])
    assert out[0].delta_vs_fastest is None


def test_guard_zero_disables_guard():
    cands = [sc("fastbike", 0, 10000, 5), sc("flow", 0, 11000, 4), sc("flow_hi", 0, 12000, 3),
             sc("flow_lo", 0, 30000, 0)]
    assert rank(list(cands), n=4)[0].cand.variant == "flow_hi"
    assert rank(list(cands), n=4, guard=0)[0].cand.variant == "flow_lo"


def sct(variant, length_m, stops, turns, straight=1.0):
    c = Candidate(variant, variant, 0, [], length_m, 0, 0, 0)
    return ScoredCandidate(c, RouteScore(expected_stops=stops, turns=turns,
                                         longest_straight_km=straight))


def test_turn_weight_zero_reproduces_stop_order():
    items = [sct("fastbike", 10000, 5, 3), sct("a", 10200, 3, 40), sct("b", 10100, 4, 2)]
    assert [s.cand.variant for s in rank(items, turn_weight=0)] == ["a", "b", "fastbike"]


def test_turn_weight_drops_turny_candidate():
    items = [sct("fastbike", 10000, 5, 3), sct("a", 10200, 3, 40), sct("b", 10100, 4, 2)]
    out = rank(items)  # default 0.33: a = 3 + 13.2, b = 4.66, fastbike = 5.99
    assert [s.cand.variant for s in out] == ["b", "fastbike", "a"]
    assert out[0].delta_vs_fastest["turns"] == -1


def test_tie_break_longest_straight_then_length():
    items = [sct("x", 10000, 2, 0, straight=1.0), sct("y", 10500, 2, 0, straight=2.0)]
    assert rank(items)[0].cand.variant == "y"


def line_cand(variant, offset_m, length_m=1000.0):
    """East-west line at 53N, offset_m north of a reference; ~1 km long."""
    import math
    lat = 53.0 + offset_m / 111_320
    dlon = length_m / (111_320 * math.cos(math.radians(53.0)))
    geom = [(-6.0 + dlon * i / 10, lat) for i in range(11)]
    return Candidate(variant, variant, 0, geom, length_m, 0, 0, 0)


def lsc(variant, offset_m, stops):
    return ScoredCandidate(line_cand(variant, offset_m), RouteScore(expected_stops=stops))


def test_diversity_skips_overlapping_and_keeps_distinct():
    items = [lsc("a", 0, 1), lsc("near", 5, 2), lsc("far", 100, 3)]
    assert [s.cand.variant for s in rank(items, n=2, guard=0)] == ["a", "far"]


def test_diversity_zero_reproduces_old_order():
    items = [lsc("a", 0, 1), lsc("near", 5, 2), lsc("far", 100, 3)]
    assert [s.cand.variant for s in rank(items, n=3, guard=0, diversity=0)] == ["a", "near", "far"]
    assert [s.cand.variant for s in rank(items, n=2, guard=0, diversity=0)] == ["a", "near"]


def test_diversity_backfills_when_pool_small():
    items = [lsc("a", 0, 1), lsc("near", 5, 2), lsc("near2", 8, 3), lsc("far", 100, 4)]
    top = rank(items, n=4, guard=0)
    assert [s.cand.variant for s in top] == ["a", "far", "near", "near2"]
    assert [s.rank for s in top] == [1, 2, 3, 4]
