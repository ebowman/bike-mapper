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
    assert out[-1].delta_vs_fastest == {"stops": 0, "km": 0}


def test_no_fastest_gives_none():
    out = rank([sc("a", 0, 1000, 1)])
    assert out[0].delta_vs_fastest is None


def test_guard_zero_disables_guard():
    cands = [sc("fastbike", 0, 10000, 5), sc("flow", 0, 11000, 4), sc("flow_hi", 0, 12000, 3),
             sc("flow_lo", 0, 30000, 0)]
    assert rank(list(cands), n=4)[0].cand.variant == "flow_hi"
    assert rank(list(cands), n=4, guard=0)[0].cand.variant == "flow_lo"
