import itertools
import threading

import pytest
from flowplan.brouter import BRouterClient, Candidate
from flowplan.candidates import DEFAULT_VARIANTS
from flowplan.plan import plan_candidates
from flowplan.scoring import haversine_m

START = (-6.2825, 53.2990)
END = (-6.1500, 53.3500)
FLOW = tuple(v for v in DEFAULT_VARIANTS if v.name == "flow")


def _perim(pts):
    return sum(haversine_m(*a, *b) for a, b in itertools.pairwise(pts))


class FakeClient(BRouterClient):
    """Route length = 1.2 x via-point polygon perimeter, straight legs. alt 1 detours sideways."""
    def __init__(self, fail_3via=False, disguise=False):
        super().__init__()
        self.calls = []
        self.lock = threading.Lock()
        self.fail_3via, self.disguise = fail_3via, disguise

    def route(self, points, profile="fastbike", alternativeidx=0, params=None):
        with self.lock:
            self.calls.append((list(points), profile, alternativeidx))
        if self.fail_3via and len(points) == 5:
            return None, "from-position not mapped"
        pts = list(points)
        if self.disguise and len(pts) > 2:
            pts = [pts[0], pts[2], pts[0]]
        geom = []
        for a, b in itertools.pairwise(pts):
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if alternativeidx == 1:
                mid = (mid[0] + 0.05, mid[1] + 0.05)
            geom += [a, mid]
        geom.append(pts[-1])
        length = 1.2 * _perim(pts)
        c = Candidate(variant=profile, profile=profile, alt=alternativeidx, geometry=geom, length_m=length,
                      ascent_m=100.0, time_s=length / 5, cost=length, params=dict(params or {}),
                      elevations=[10.0 + i for i in range(len(geom))])
        return c, None


def test_loop_converges_in_range():
    cl = FakeClient()
    res = plan_candidates(cl, "loop", START, length_km=(40, 50), bearings=4, variants=None or
                          FLOW)
    assert res.kept and res.calls == len(cl.calls)
    for c in res.kept:
        assert 40 <= c.plan["length_km"] <= 50
        assert c.plan["mode"] == "loop" and c.plan["iterations"] <= 3
        assert len(c.plan["via_points"]) == 3 and c.plan["radius_m"] > 0
    assert any(c.plan["iterations"] >= 2 for c in res.kept)


def test_loop_all_variants_budget():
    cl = FakeClient()
    res = plan_candidates(cl, "loop", START, length_km=(40, 50), bearings=2)
    assert res.calls == len(cl.calls) <= 48
    assert {c.plan["heading_deg"] for c in res.kept + res.dropped} <= {0.0, 180.0}


def test_loop_two_via_fallback():
    cl = FakeClient(fail_3via=True)
    res = plan_candidates(cl, "loop", START, length_km=(40, 50), bearings=2)
    assert res.kept
    assert all(len(c.plan["via_points"]) == 2 for c in res.kept)
    assert all(40 <= c.plan["length_km"] <= 50 for c in res.kept)


def test_out_and_back_same_palindromic():
    cl = FakeClient()
    res = plan_candidates(cl, "out-and-back", START, length_km=(50, 60), bearings=2)
    assert res.kept
    for c in res.kept:
        assert c.geometry == c.geometry[::-1]
        assert c.elevations == c.elevations[::-1]
        assert 50 <= c.length_m / 1000 <= 60
        assert c.plan["return_mode"] == "same" and c.plan["turnaround"]


def test_out_and_back_explicit_end_doubles():
    cl = FakeClient()
    res = plan_candidates(cl, "out-and-back", START, END, length_km=(1, 100), variants=FLOW)
    assert len(res.kept) == 1 and res.calls == 1
    c = res.kept[0]
    assert c.length_m == pytest.approx(2 * 1.2 * haversine_m(*START, *END))
    assert c.geometry[0] == START and END in c.geometry and c.plan["turnaround"] == list(END)


def test_out_and_back_free_uses_different_return():
    cl = FakeClient()
    res = plan_candidates(cl, "out-and-back", START, END, length_km=(1, 500), variants=FLOW, return_mode="free")
    c = res.kept[0]
    assert c.plan["return_mode"] == "free" and res.calls == 2
    assert c.geometry != c.geometry[::-1]
    assert any(a == 1 for _, _, a in cl.calls)


def test_free_falls_back_on_overlap():
    class Same(FakeClient):
        def route(self, points, profile="fastbike", alternativeidx=0, params=None):
            return super().route(points, profile, 0, params)
    res = plan_candidates(Same(), "out-and-back", START, END, length_km=(1, 500),
                          variants=FLOW, return_mode="free")
    c = res.kept[0]
    assert c.plan["return_mode"] == "same" and c.geometry == c.geometry[::-1]
    assert any("overlaps" in n for n in res.notes)


def test_max_calls_respected():
    cl = FakeClient()
    res = plan_candidates(cl, "loop", START, length_km=(40, 50), bearings=8, max_calls=5)
    assert res.calls == len(cl.calls) == 5
    assert any("max_calls" in n for n in res.notes)


def test_one_way_passthrough():
    cl = FakeClient()
    res = plan_candidates(cl, "one-way", START, END, length_km=(10, 20))
    assert res.calls == len(cl.calls) == 4
    assert len(res.kept) + len(res.dropped) == 4
    assert all(c.plan["mode"] == "one-way" for c in res.kept)
    assert any("not enforced" in n for n in res.notes)


def test_disguised_out_and_back_loop_dropped():
    res = plan_candidates(FakeClient(disguise=True), "loop", START, length_km=(1, 500), bearings=2,
                          variants=FLOW)
    assert not res.kept and res.dropped
    assert all("out-and-back" in c.duplicate_of for c in res.dropped)


def test_bad_args():
    with pytest.raises(ValueError):
        plan_candidates(FakeClient(), "loop", START, length_km=(50, 40))
    with pytest.raises(ValueError):
        plan_candidates(FakeClient(), "spiral", START)
