import itertools
import math
import threading

import pytest
from flowplan import plan as plan_mod
from flowplan.brouter import BRouterClient, Candidate
from flowplan.candidates import DEFAULT_VARIANTS
from flowplan.plan import plan_candidates
from flowplan.scoring import REGION_CRS, haversine_m
from pyproj import Transformer

from tests.test_terrain import START as DEM_START
from tests.test_terrain import make_dem

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
    assert res.calls == len(cl.calls) <= 72
    assert {c.plan["heading_deg"] for c in res.kept + res.dropped} <= {0.0, 90.0, 180.0}   # rings + one petal at the half-step offset


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


# ---- objectives (41w.4) ----
def _hill_dem(tmp_path):
    import numpy as np
    import rasterio
    from flowplan.terrain import Dem
    from rasterio.transform import from_origin
    step = 0.002
    n = int(1 / step)
    lons = -7 + (np.arange(n) + 0.5) * step
    lats = 54 - (np.arange(n) + 0.5) * step
    LO, LA = np.meshgrid(lons, lats)
    d2 = ((LO - (-6.30)) * 66000) ** 2 + ((LA - 53.38) * 111000) ** 2
    z = (50 + 400 * np.exp(-d2 / (2 * 3000.0 ** 2))).astype("float32")
    p = tmp_path / "h.tif"
    with rasterio.open(p, "w", driver="GTiff", height=n, width=n, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(-7, 54, step, step)) as ds:
        ds.write(z, 1)
    return Dem(paths=[p])


def test_climb_loop_uses_top_hill_vias(tmp_path):
    from flowplan.terrain import climb_via_points
    dem = _hill_dem(tmp_path)
    cl = FakeClient()
    res = plan_candidates(cl, "loop", START, length_km=(40, 50), bearings=4, variants=FLOW,
                          objective="climb", dem=dem)
    assert res.kept
    res.kept = [c for c in res.kept if c.plan["shape"] == "ring"]
    d0 = 45 * 1000 / (2 * 3.141592653589793) * 1.15
    top = climb_via_points(dem, START, d0)
    best = max(p.score for p in top)
    for c in res.kept:
        assert c.plan["objective"] == "climb" and len(c.plan["via_scores"]) in (2, 3)
        assert 40 <= c.plan["length_km"] <= 50
    # the best set contains the very top-scoring grid point's score
    assert max(max(c.plan["via_scores"]) for c in res.kept) == pytest.approx(best, abs=0.2)


def test_climb_loop_bearings_spread(tmp_path):
    from flowplan.plan import _bsep
    res = plan_candidates(FakeClient(), "loop", START, length_km=(40, 50), bearings=3, variants=FLOW,
                          objective="climb", dem=_hill_dem(tmp_path))
    assert res.kept and all(c.plan["n_via"] == 3 for c in res.kept)
    import math
    for c in (c for c in res.kept if c.plan["shape"] == "ring"):
        brg = [math.degrees(math.atan2(v[0] - START[0], v[1] - START[1])) % 360 for v in c.plan["via_points"]]
        # lon/lat deltas are only roughly conformal here; allow slack around the 60 degree rule
        assert all(_bsep(a, b) >= 45 for a in brg for b in brg if a is not b)


def test_climb_out_and_back(tmp_path):
    res = plan_candidates(FakeClient(), "out-and-back", START, length_km=(50, 60), bearings=3, variants=FLOW,
                          objective="climb", dem=_hill_dem(tmp_path))
    assert res.kept
    for c in res.kept:
        assert c.plan["objective"] == "climb" and len(c.plan["via_scores"]) == 1
        assert 50 <= c.length_m / 1000 <= 60 and c.geometry == c.geometry[::-1]
    # hill is NE of START: the best-scoring turnaround heads roughly east of north
    best = max(res.kept, key=lambda c: c.plan["via_scores"][0])
    from flowplan.plan import _bsep
    assert _bsep(best.plan["heading_deg"], 10) <= 60


def test_flat_objective_labels(tmp_path):
    res = plan_candidates(FakeClient(), "loop", START, length_km=(40, 50), bearings=2, variants=FLOW,
                          objective="flat", dem=_hill_dem(tmp_path))
    assert res.kept and all(c.plan["objective"] == "flat" and max(c.plan["via_scores"]) <= 0 for c in res.kept)


def test_objective_fallback_when_dem_missing(tmp_path):
    from flowplan.terrain import Dem
    res = plan_candidates(FakeClient(), "loop", START, length_km=(40, 50), bearings=2, variants=FLOW,
                          objective="climb", dem=Dem(dem_dir=tmp_path))
    assert res.kept and all(c.plan["objective"] == "flow" for c in res.kept)
    assert any("evenly spaced" in n for n in res.notes)


def test_bad_objective():
    with pytest.raises(ValueError):
        plan_candidates(FakeClient(), "loop", START, objective="swoop")


# ---- petal loops, bracketing, nearest candidates, disguise rule ----
_TF = Transformer.from_crs("EPSG:4326", REGION_CRS["ireland"], always_xy=True)


def _xy(p):
    return _TF.transform(*p)


def _polar(start, p):
    sx, sy = _xy(start)
    x, y = _xy(p)
    return math.degrees(math.atan2(x - sx, y - sy)) % 360, math.hypot(x - sx, y - sy)


def _first_round(cl, n):
    """Via lists (start/end stripped) of the first n BRouter calls (round 1)."""
    return [c[0][1:-1] for c in cl.calls[:n]]


def _is_petal(vias, start=START):
    d = [_polar(start, v)[1] for v in vias]
    return len(vias) == 3 and d[1] > d[0] * 1.1


def test_petal_state_per_heading_geometry():
    cl = FakeClient()
    res = plan_candidates(cl, "loop", START, length_km=(40, 50), bearings=4, variants=FLOW)
    first = _first_round(cl, 6)
    petals = [v for v in first if _is_petal(v)]
    assert len(petals) == 2 and len(first) - len(petals) == 4   # 4 rings + bearings // 2 petals
    seen = set()
    for vias in petals:
        (b0, d0), (b1, d1), (b2, d2) = (_polar(START, v) for v in vias)
        theta = (round((b1 - 45) / 180) * 180 + 45) % 360
        seen.add(theta)
        assert abs((b0 - (theta - 35) + 180) % 360 - 180) < 0.5
        assert abs((b2 - (theta + 35) + 180) % 360 - 180) < 0.5
        assert d1 / d0 == pytest.approx(1 / 0.75, rel=0.01) and d1 / d2 == pytest.approx(1 / 0.75, rel=0.01)
        pts = [START, *vias, START]
        perim = sum(math.dist(_xy(a), _xy(b)) for a, b in itertools.pairwise(pts))
        assert perim == pytest.approx(45000 / plan_mod.ROAD_RATIO, rel=0.01)
    assert seen == {45, 225}   # half a ring step off the ring headings
    shapes = {c.plan["shape"] for c in res.kept + res.dropped}
    assert shapes <= {"ring", "petal"} and "petal" in shapes
    ids = [(c.plan["heading_deg"], c.plan["set"]) for c in res.kept + res.dropped]
    assert len(ids) == len(set(ids))


def test_petal_dem_centres_beyond_ring(tmp_path):
    dem = make_dem(tmp_path)
    cl = FakeClient()
    res = plan_candidates(cl, "loop", DEM_START, length_km=(20, 30), bearings=3, variants=FLOW,
                          objective="climb", dem=dem, max_calls=72)
    ring_r = 25000 / (2 * math.pi) * plan_mod.DETOUR
    petal_c = [c for c in res.kept + res.dropped if c.plan["shape"] == "petal"]
    first = _first_round(cl, len({c.plan["set"] for c in res.kept + res.dropped}))
    far = [max(_polar(DEM_START, v)[1] for v in vias) for vias in first if _is_petal(vias, DEM_START)]
    assert far and max(far) > 1.2 * ring_r
    assert petal_c and all(c.plan["objective"] == "climb" and len(c.plan["via_scores"]) == 1 for c in petal_c)


class _Steep(FakeClient):
    """Length 10 km below max via distance 7 km, rising linearly to 80 km at 13 km (continuous but steep)."""
    def route(self, points, profile="fastbike", alternativeidx=0, params=None):
        c, err = super().route(points, profile, alternativeidx, params)
        r = max(haversine_m(*points[0], *p) for p in points[1:-1])
        km = 10 + 70 * min(1.0, max(0.0, (r - 7000) / 6000))
        c.length_m = km * 1000
        return c, err


def test_bracketing_converges():
    res = plan_candidates(_Steep(), "loop", START, length_km=(40, 50), bearings=2, variants=FLOW)
    assert res.kept
    assert all(40 <= c.plan["length_km"] <= 50 for c in res.kept)
    ring = [c for c in res.kept if c.plan["shape"] == "ring"]
    assert ring and all(c.plan["iterations"] == 4 for c in ring)   # 24, 80 (x2 cap), 59, bracketed 40.3 km


class _Const(FakeClient):
    def __init__(self, km):
        super().__init__()
        self.km = km

    def route(self, points, profile="fastbike", alternativeidx=0, params=None):
        c, err = super().route(points, profile, alternativeidx, params)
        c.length_m = self.km * 1000
        return c, err


def test_nearest_candidates_when_all_overshoot():
    res = plan_candidates(_Const(60), "loop", START, length_km=(40, 50), bearings=3, variants=FLOW)
    assert res.kept and any("returning the nearest" in n for n in res.notes)
    assert all(c.plan["length_km"] == pytest.approx(60) and c.plan["near"] for c in res.kept)
    assert not any("no candidate inside" in n for n in res.notes)


def test_no_nearest_when_far_outside():
    res = plan_candidates(_Const(75), "loop", START, length_km=(40, 50), bearings=3, variants=FLOW)
    assert not res.kept and any("no candidate inside the requested length range" in n for n in res.notes)
    assert not any("returning the nearest" in n for n in res.notes)


def test_collapsed_loops_never_nearest():
    res = plan_candidates(_Const(5), "loop", START, length_km=(15, 20), bearings=2, variants=FLOW)
    assert not res.kept
    assert any(s["error"] == "collapsed (coast/peninsula)" for s in res.skipped)


def test_petal_overlap_threshold(monkeypatch):
    monkeypatch.setattr(plan_mod, "_overlap", lambda a, b, tf, buffer_m=20.0: 0.7)
    res = plan_candidates(FakeClient(), "loop", START, length_km=(40, 50), bearings=1, variants=FLOW)
    assert res.kept and all(c.plan["shape"] == "petal" and c.plan["overlap_pct"] == 70 for c in res.kept)
    assert res.dropped and all(c.plan["shape"] == "ring" for c in res.dropped)


class _Long(FakeClient):
    """Route length = 1.5 x the FakeClient length, so the first measurement is ~1.35-1.6 x the target."""
    def route(self, points, profile="fastbike", alternativeidx=0, params=None):
        c, err = super().route(points, profile, alternativeidx, params)
        c.length_m *= 1.5
        return c, err


def test_dem_petal_keeps_centre_and_narrows_spread_first(tmp_path):
    from flowplan.terrain import climb_via_points
    dem = make_dem(tmp_path)
    cl = _Long()
    res = plan_candidates(cl, "loop", DEM_START, length_km=(35, 45), bearings=4, variants=FLOW,
                          objective="climb", dem=dem)
    pts = climb_via_points(dem, DEM_START, plan_mod._petal_reach(40000), radii=plan_mod.PETAL_RADII)
    petals = [c for c in res.kept if c.plan["shape"] == "petal"]
    assert petals and all(35 <= c.plan["length_km"] <= 45 for c in petals)
    # first shrink step: the spread narrows while rho stays at 0.75
    assert any(c.plan["spread_deg"] < 35 and c.plan["rho"] == 0.75 for c in petals)
    # ... and the centre via is still exactly the chosen DEM point for those
    held = [c for c in petals if c.plan["rho"] == 0.75 and c.plan["spread_deg"] < 35]
    assert held and all(any(haversine_m(*c.plan["via_points"][1], p.lon, p.lat) < 1.0 for p in pts) for c in held)


def test_petal_fit_order_and_monotonic():
    pers = [plan_mod._perimeter(plan_mod._petal_polar(0.0, 1.0, *plan_mod._petal_path(t / 100)))
            for t in range(201)]
    assert all(a >= b - 1e-9 for a, b in itertools.pairwise(pers))
    rho, spread, k = plan_mod._petal_fit(0.9 * 2.655 * 1000, 1000)    # slightly short of full: spread only
    assert rho == 0.75 and spread < 35 and k == 1.0
    rho, spread, k = plan_mod._petal_fit(2.03 * 1000, 1000)           # spread at minimum, rho shrinking
    assert spread == plan_mod.SPREAD_MIN and rho < 0.75 and k == 1.0
    rho, spread, k = plan_mod._petal_fit(1.0 * 1000, 1000)            # below the thin end: centre scales
    assert (rho, spread) == (plan_mod.RHO_MIN, plan_mod.SPREAD_MIN) and k < 1.0
    assert plan_mod._petal_fit(3.5 * 1000, 1000)[2] > 1.0


def test_dem_petal_centres_within_reach_and_initial_shape():
    target_m = 40000
    reach = plan_mod._petal_reach(target_m)
    assert reach == pytest.approx(target_m / plan_mod.ROAD_RATIO / plan_mod.PERIMETER_MIN)
    assert max(plan_mod.PETAL_RADII) * reach <= reach
    perim = target_m / plan_mod.ROAD_RATIO
    rho, spread, k = plan_mod._petal_fit(perim, 0.95 * reach)      # far centre: narrow start, centre kept
    assert spread < plan_mod.PETAL_SPREAD and k == pytest.approx(1.0)
    rho, spread, k = plan_mod._petal_fit(perim, 0.5 * reach)       # near centre: full spread
    assert (rho, spread) == (plan_mod.PETAL_RHO, plan_mod.PETAL_SPREAD)
    # perimeter of the fitted shape matches the sizing target when the centre can stay put
    r0, sp0, k0 = plan_mod._petal_fit(perim, 0.8 * reach)
    got = 0.8 * reach * k0 * plan_mod._perimeter(plan_mod._petal_polar(0.0, 1.0, r0, sp0))
    assert got == pytest.approx(perim, rel=0.01)


def test_dem_petal_state_centres_never_beyond_reach(tmp_path):
    dem = make_dem(tmp_path)
    reach = plan_mod._petal_reach(40000)
    sts = plan_mod._objective_states("climb", "loop", dem, DEM_START, 1.0, 4, "ireland", plan_mod.PlanResult(), 40000)
    cs = [s.centre for s in sts if s.lever]
    assert cs and all(c <= reach + 1e-6 for c in cs)
