"""Loop and out-and-back candidate generation targeting a length range (via-point rings, radius iteration).

LOOP: start -> v1 -> v2 -> v3 -> start, with the vias on a ring of radius r around the start at bearings
theta, theta+120, theta+240 (2-via fallback: theta, theta+180). r starts at target/(2*pi) * DETOUR (the
circle radius for the target length, inflated by the road detour factor) and is rescaled by
target/measured after each BRouter call, at most MAX_ITER calls per heading, stopping once the measured
length lies in [min, max]. OUT-AND-BACK: a turnaround at distance d = target/2 * DETOUR along theta (or the
explicit end); the same iteration.
PETAL loops (start -> v1 -> v2 -> v3 -> start with the vias fanned around ONE heading: theta-35, theta, theta+35 at
0.75 / 1 / 0.75 x d) reach hills outside the ring and close from a peninsula. ONE-WAY: plain candidates.generate.
"""
from __future__ import annotations

import itertools
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

import shapely
from pyproj import Transformer

from .brouter import BRouterClient, Candidate, validate_params
from .candidates import DEFAULT_VARIANTS, DEFAULT_WORKERS, Variant, dedupe, generate
from .scoring import REGION_CRS
from .terrain import Dem, climb_via_points, flat_via_points

__all__ = ["DETOUR", "MAX_ITER", "PlanResult", "plan_candidates"]

# Roads are longer than the crow-flies figure they wrap; 15% is a typical suburban/rural detour factor.
DETOUR = 1.15
MAX_ITER = 4
PETAL_SPREAD = 35.0           # petal side vias sit this many degrees either side of the centre via
PETAL_RHO = 0.75              # ... at this fraction of the centre via's distance
NEAR_RANGE_TOL = 0.25         # nearest-candidate fallback: within this x target of the nearer range bound
RHO_MIN = 0.3                 # DEM-centred petals narrow to SPREAD_MIN first, then pull the sides in to this fraction ...
SPREAD_MIN = 8.0              # ... of the centre distance, and only then move the centre itself
ITER_BUDGET_FRAC = 0.7        # length targeting may spend at most this x max_calls; the rest is for variants/returns
COLLAPSE_FRAC = 0.5           # a loop shorter than this x target has collapsed onto the coast
# Measured road length / crow-flies perimeter of loops around Dublin (1.6-1.9 observed): petals are sized with
# this, not with the suburban DETOUR that the rings keep.
ROAD_RATIO = 1.6
LOOP_DISGUISE_OVERLAP = 0.6   # loops whose out and back legs overlap more than this are out-and-backs
LOOP_DISGUISE_OVERLAP_PETAL = 0.8   # petals from a peninsula legitimately share their stem
FREE_RETURN_OVERLAP = 0.7     # 'free' return overlapping the out leg more than this falls back to 'same'
OVERLAP_BUFFER_M = 20.0
# perimeter / r of start->v1->v2->v3->start (ring around start) and of the 2-via start->v1->v2->start
_K3 = 2 * (1 + math.sqrt(3))
_K2 = 4.0


@dataclass
class PlanResult:
    kept: list = field(default_factory=list)
    dropped: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    calls: int = 0
    notes: list = field(default_factory=list)


@dataclass
class _State:
    heading: float
    param: float            # ring radius r (loop) or turnaround distance d (out-and-back), metres
    n_via: int = 3
    iters: int = 0
    done: bool = False
    ok: bool = False
    error: str = ""
    cand: Candidate | None = None
    km: float = 0.0         # measured total length (loop: route; out-and-back: 2 x out leg)
    points: list = field(default_factory=list)
    fixed: bool = False     # explicit turnaround: no iteration, no range enforcement
    polar: list = field(default_factory=list)   # objective sets: [(bearing_deg, dist_m)] at scale 1 (param == param0)
    param0: float = 0.0
    scores: list = field(default_factory=list)  # objective sets: via-point scores
    idx: int = 0            # via-point set index (generation order, unique across ring and petal states)
    shape: str = "ring"     # 'ring' | 'petal'
    hist: list = field(default_factory=list)   # [(param, km)] measurements, for bracketing
    lever: bool = False     # DEM-centred petal: param is the crow-flies perimeter; sides move before the centre
    centre: float = 0.0     # lever petals: distance of the DEM centre point at scale 1
    rho: float = PETAL_RHO  # lever petals: current side distance fraction
    spread: float = PETAL_SPREAD   # lever petals: current side spread, degrees
    dist: float = 0.0       # lever petals: current centre distance
    fails: int = 0          # lever petals: routing failures after a successful measurement
    near: bool = False      # kept as a nearest candidate although outside the requested range


def _overlap(a_geom, b_geom, tf, buffer_m=OVERLAP_BUFFER_M) -> float:
    """Fraction of b's length lying within buffer_m of a."""
    if len(a_geom) < 2 or len(b_geom) < 2:
        return 0.0
    la = shapely.linestrings(list(zip(*tf.transform([p[0] for p in a_geom], [p[1] for p in a_geom]))))
    lb = shapely.linestrings(list(zip(*tf.transform([p[0] for p in b_geom], [p[1] for p in b_geom]))))
    if lb.length <= 0:
        return 0.0
    return shapely.intersection(lb, shapely.buffer(la, buffer_m)).length / lb.length


def _split_halves(geom, tf):
    xs, ys = tf.transform([p[0] for p in geom], [p[1] for p in geom])
    cum = [0.0]
    for i in range(1, len(xs)):
        cum.append(cum[-1] + math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]))
    i = next((k for k, c in enumerate(cum) if c >= cum[-1] / 2), len(geom) - 1)
    return geom[:i + 1], geom[i:]


def _same_return(out: Candidate) -> Candidate:
    """Out leg + its reverse: palindromic geometry, doubled length; ascent of the return = out descent."""
    el = out.elevations
    have_el = bool(el) and el[0] is not None and el[-1] is not None
    back_asc = max(0.0, out.ascent_m - (el[-1] - el[0])) if have_el else out.ascent_m
    return replace(out, geometry=out.geometry + out.geometry[::-1][1:],
                   elevations=(el + el[::-1][1:]) if el else [],
                   length_m=out.length_m * 2, ascent_m=out.ascent_m + back_asc, time_s=out.time_s * 2,
                   cost=out.cost * 2, segments=out.segments + out.segments[::-1])


def _free_return(out: Candidate, back: Candidate) -> Candidate:
    return replace(out, geometry=out.geometry + back.geometry[1:],
                   elevations=(out.elevations + back.elevations[1:]) if out.elevations and back.elevations else [],
                   length_m=out.length_m + back.length_m, ascent_m=out.ascent_m + back.ascent_m,
                   time_s=out.time_s + back.time_s, cost=out.cost + back.cost,
                   segments=out.segments + back.segments)


def plan_candidates(client: BRouterClient, mode: str, start, end=None, length_km=(40.0, 50.0),
                    bearings: int = 8, variants=DEFAULT_VARIANTS, alts=(0,), max_calls: int = 72,
                    profile_params: dict | None = None, region: str = "ireland",
                    return_mode: str = "same", progress=None, objective: str = "flow",
                    dem: Dem | None = None) -> PlanResult:
    """mode: 'loop' | 'out-and-back' | 'one-way'. length_km = (min, max) total route length.
    progress(calls, max_calls, message) is called after each BRouter round. BRouterUnavailable propagates.
    Every BRouter request counts against max_calls; the result carries what was found plus notes.
    objective: 'flow' (evenly spaced headings) | 'climb' | 'flat' (loops and out-and-backs: via-points picked
    from the DEM, see flowplan.terrain; falls back to 'flow' headings with a note when coverage is too thin)."""
    if mode not in ("loop", "out-and-back", "one-way"):
        raise ValueError(f"mode must be loop, out-and-back or one-way, got {mode!r}")
    if return_mode not in ("same", "free"):
        raise ValueError(f"return_mode must be same or free, got {return_mode!r}")
    if objective not in ("flow", "climb", "flat"):
        raise ValueError(f"objective must be flow, climb or flat, got {objective!r}")
    lo, hi = float(length_km[0]), float(length_km[1])
    if not (math.isfinite(lo) and math.isfinite(hi) and 0 < lo <= hi):
        raise ValueError(f"length_km must be 0 < min <= max, got {length_km!r}")
    start = (float(start[0]), float(start[1]))
    if region not in REGION_CRS:
        raise ValueError(f"unknown region {region!r}; known: {', '.join(REGION_CRS)}")
    variants, alts = tuple(variants), tuple(alts)
    if not variants or not alts:
        raise ValueError("need at least one variant and one alt")
    if profile_params:
        variants = tuple(Variant(v.name, v.profile, {**profile_params, **v.params}) for v in variants)
    for v in variants:
        validate_params(v.params)
    res = PlanResult()
    target = (lo + hi) / 2

    if mode == "one-way":
        if objective != "flow":
            res.notes.append(f"objective {objective!r} does not apply to one-way routes")
        return _one_way(client, res, start, end, variants, alts, max_calls, region, lo, hi)
    if bearings < 1:
        raise ValueError("bearings must be >= 1")

    tf = Transformer.from_crs("EPSG:4326", REGION_CRS[region], always_xy=True)
    inv = Transformer.from_crs(REGION_CRS[region], "EPSG:4326", always_xy=True)
    sx, sy = tf.transform(*start)

    def at(theta, dist):
        t = math.radians(theta)
        return tuple(inv.transform(sx + dist * math.sin(t), sy + dist * math.cos(t)))

    def build(s: _State):
        if s.fixed:
            return
        if s.lever:
            s.rho, s.spread, k = _petal_fit(s.param, s.centre)
            s.dist = s.centre * k
            s.polar = _petal_polar(s.heading, s.dist, s.rho, s.spread)
            vias = [at(t, d) for t, d in s.polar[:s.n_via]]
            s.points = [start, *vias, start]
        elif s.polar:
            k = s.param / s.param0      # radial scale applied to the chosen via-points about the start
            vias = [at(t, d * k) for t, d in s.polar[:s.n_via if mode == "loop" else 1]]
            s.points = [start, *vias, start] if mode == "loop" else [start, vias[0]]
        elif mode == "loop":
            offs = (0, 120, 240) if s.n_via == 3 else (0, 180)
            vias = [at(s.heading + o, s.param) for o in offs]
            s.points = [start, *vias, start]
        else:
            s.points = [start, at(s.heading, s.param)]

    it_var = next((v for v in variants if v.name == "flow"), variants[0])
    it_alt = alts[0]
    workers = DEFAULT_WORKERS

    def run_round(jobs, cap=None):
        """jobs: [(points, variant, alt)] -> results; counts calls, truncates to the budget (or to cap)."""
        room = (max_calls if cap is None else cap) - res.calls
        if len(jobs) > room:
            if ("call budget" if cap is None else "length-targeting budget") not in " ".join(res.notes):
                res.notes.append(f"call budget max_calls={max_calls} reached; results are partial" if cap is None else
                                 f"length-targeting budget ({cap} of max_calls={max_calls} calls) reached; "
                                 "some headings were not sized")
            jobs = jobs[:max(room, 0)]
        if not jobs:
            return []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            out = list(ex.map(lambda j: client.route(j[0], j[1].profile, j[2], j[1].params), jobs))
        res.calls += len(jobs)
        return out

    def report(msg):
        if progress:
            progress(res.calls, max_calls, msg)

    # ---- states ----
    if mode == "out-and-back" and end is not None:
        end = (float(end[0]), float(end[1]))
        if end == start:
            res.notes.append("start == end: no out-and-back")
            return res
        if objective != "flow":
            res.notes.append(f"objective {objective!r} does not apply to an out-and-back with an explicit end")
        ex_, ey_ = tf.transform(*end)
        brg = math.degrees(math.atan2(ex_ - sx, ey_ - sy)) % 360
        states = [_State(brg, math.hypot(ex_ - sx, ey_ - sy), points=[start, end], fixed=True)]
    else:
        if mode == "out-and-back" and end is None:
            d0 = target * 1000 / 2 * DETOUR
        else:
            d0 = target * 1000 / (2 * math.pi) * DETOUR
        states = None
        if objective != "flow":
            states = _objective_states(objective, mode, dem, start, d0, bearings, region, res,
                                       target * 1000)
        if not states:
            states = [_State(i * 360.0 / bearings, d0) for i in range(bearings)]
            if mode == "loop":
                n_p = max(1, bearings // 2)     # half the ring count, offset half a ring step
                states += [_petal_state(360.0 / bearings / 2 + i * 360.0 / n_p, target * 1000) for i in range(n_p)]
        for s in states:
            build(s)
    for i, s in enumerate(states):
        s.idx = i   # stable via-point-set index (generation order), part of the route id
    total_factor = 2 if mode == "out-and-back" else 1

    def km_of(c):
        return c.length_m * total_factor / 1000

    def in_range(s, km):
        if lo <= km <= hi:
            return True
        return s.near and (lo - km if km < lo else km - hi) <= NEAR_RANGE_TOL * target

    # ---- iteration with the flow variant ----
    for rnd in range(MAX_ITER + 4):
        todo = sorted((s for s in states if not s.done), key=lambda s: s.shape != "petal")   # petals first if the budget bites
        if not todo:
            break
        results = run_round([(s.points, it_var, it_alt) for s in todo], cap=int(ITER_BUDGET_FRAC * max_calls))
        if not results:
            break
        for s, (c, err) in zip(todo, results):
            if c is None:
                if s.lever and s.hist and s.fails < 1:
                    # a narrower petal put a via in the sea (peninsula): back off towards the last size that routed
                    s.fails += 1
                    s.param = math.sqrt(s.param * s.hist[-1][0])
                    build(s)
                    continue
                if mode == "loop" and s.n_via == 3:
                    s.n_via = 2
                    if not s.polar:     # DEM sets keep their radial scale and drop to their first two vias
                        s.param *= _K3 / _K2
                    build(s)
                    continue
                s.done, s.error = True, err or "no route"
                continue
            c.variant = it_var.name
            s.iters += 1
            s.cand, s.km = c, km_of(c)
            s.hist.append((s.param, s.km))
            if s.fixed:
                s.done = s.ok = True
                if not lo <= s.km <= hi:
                    res.notes.append(f"explicit turnaround gives {s.km:.1f} km, outside {lo:g}-{hi:g} km")
            elif lo <= s.km <= hi:
                s.done = s.ok = True
            elif s.iters >= MAX_ITER:
                s.done = True
                s.error = ("collapsed (coast/peninsula)" if s.km < COLLAPSE_FRAC * target else
                           f"length {s.km:.1f} km outside {lo:g}-{hi:g} km after {s.iters} iterations")
            else:
                below = [(k, p) for p, k in s.hist if k < lo]
                above = [(k, p) for p, k in s.hist if k > hi]
                if below and above:     # bracketed: geometric mean of the closest measurements either side
                    s.param = math.sqrt(max(below)[1] * min(above)[1])
                else:
                    s.param *= min(2.0, max(0.5, target / max(s.km, 1e-6)))
                build(s)
        report(f"round {rnd + 1}: {sum(s.ok for s in states)}/{len(states)} headings in range")
    for s in states:
        if not s.done:
            s.done, s.error = True, "call budget exhausted"
    if not any(s.ok for s in states) and not any(s.fixed for s in states):
        near = sorted((s for s in states if s.cand is not None and s.km >= COLLAPSE_FRAC * target),
                      key=lambda s: lo - s.km if s.km < lo else s.km - hi)
        near = [s for s in near if (lo - s.km if s.km < lo else s.km - hi) <= NEAR_RANGE_TOL * target][:3]
        if near:
            for s in near:
                s.ok = s.near = True
                s.error = ""
            res.notes.append(f"no loop inside {lo:g}-{hi:g} km from this start; returning the nearest "
                             f"({', '.join(f'{s.km:.1f}' for s in near)} km) - try a wider range")
    for s in states:
        if not s.ok:
            res.skipped.append({"variant": it_var.name, "alt": it_alt, "heading_deg": s.heading, "error": s.error})

    # ---- other variants / alts at each converged heading ----
    entries = [(s, it_var, it_alt, s.cand) for s in states if s.ok]
    extra = [(s, v, a) for v in variants for a in alts if (v.name, a) != (it_var.name, it_alt) for s in states if s.ok]
    results = run_round([(s.points, v, a) for s, v, a in extra])
    for (s, v, a), (c, err) in zip(extra, results):
        if c is None:
            res.skipped.append({"variant": v.name, "alt": a, "heading_deg": s.heading, "error": err or "no route"})
            continue
        c.variant = v.name
        if not s.fixed and not in_range(s, km_of(c)):
            res.skipped.append({"variant": v.name, "alt": a, "heading_deg": s.heading,
                                "error": f"length {km_of(c):.1f} km outside {lo:g}-{hi:g} km"})
            continue
        entries.append((s, v, a, c))
    if len(results) < len(extra):
        res.skipped.extend({"variant": v.name, "alt": a, "heading_deg": s.heading, "error": "call budget exhausted"}
                           for s, v, a in extra[len(results):])
    report(f"{len(entries)} candidates before dedupe")

    # ---- returns (out-and-back) ----
    cands = []
    free = {}
    if mode == "out-and-back" and return_mode == "free":
        jobs = [(list(reversed(s.points)), v, 1) for s, v, a, c in entries]
        back = run_round(jobs)
        free = {i: r for i, r in enumerate(back)}
    for i, (s, v, a, c) in enumerate(entries):
        ret = "same"
        if mode == "out-and-back":
            out = c
            full = _same_return(out)
            if return_mode == "free":
                b = free.get(i)
                if b is None or b[0] is None:
                    res.notes.append(f"free return unavailable at {s.heading:g} deg ({v.name}); using same")
                else:
                    ov = _overlap(out.geometry, b[0].geometry, tf)
                    cand_free = _free_return(out, b[0])
                    if ov > FREE_RETURN_OVERLAP:
                        res.notes.append(f"free return overlaps out leg {ov:.0%} at {s.heading:g} deg ({v.name}); using same")
                    elif not s.fixed and not in_range(s, cand_free.length_m / 1000):
                        res.notes.append(f"free return length {cand_free.length_m / 1000:.1f} km outside range at "
                                         f"{s.heading:g} deg ({v.name}); using same")
                    else:
                        full, ret = cand_free, "free"
            c = full
        c.variant, c.alt = v.name, a
        plan = {"mode": mode, "heading_deg": s.heading, "set": s.idx, "via_points": [list(p) for p in s.points[1:-1]]
                if mode == "loop" else [], "iterations": s.iters, "length_km": round(c.length_m / 1000, 3),
                "n_via": s.n_via if mode == "loop" else None}
        if mode == "loop":
            plan["radius_m"] = round(s.dist if s.lever else s.param, 1)
            plan["shape"] = s.shape
            if s.lever:
                plan["rho"] = round(s.rho, 2)
                plan["spread_deg"] = round(s.spread, 1)
        else:
            plan["turnaround"] = list(s.points[-1])
            plan["distance_m"] = round(s.param, 1)
            plan["return_mode"] = ret
        if s.near:
            plan["near"] = True
        plan["objective"] = objective if s.scores else "flow"
        if s.scores:
            plan["via_scores"] = [round(x, 1) for x in s.scores]
        c.plan = plan
        cands.append(c)

    # ---- drop disguised out-and-backs, then dedupe (keys made unique per via-point set) ----
    if mode == "loop":
        keep = []
        for c in cands:
            a_, b_ = _split_halves(c.geometry, tf)
            ov = _overlap(a_, b_, tf)
            c.plan["overlap_pct"] = round(ov * 100)
            limit = LOOP_DISGUISE_OVERLAP_PETAL if c.plan.get("shape") == "petal" else LOOP_DISGUISE_OVERLAP
            if ov > limit:
                c.duplicate_of = f"out-and-back ({ov:.0%} overlap)"
                res.dropped.append(c)
            else:
                keep.append(c)
        cands = keep
    names = {id(c): c.variant for c in cands}
    for c in cands:
        c.variant = f"{c.variant}@{c.plan['heading_deg']:g}.{c.plan['set']}"
    kept, dropped = dedupe(cands, region)
    for c in cands:
        c.variant = names[id(c)]
    # duplicate_of keeps the '@heading.set' so it equals the kept candidate's route_id
    res.kept, res.dropped = kept, res.dropped + dropped
    if not kept:
        res.notes.append("no candidate inside the requested length range")
    return res


MIN_OBJECTIVE_POINTS = 6   # fewer DEM-covered candidate points than this: fall back to even headings
MIN_BEARING_SEP = 60.0     # loop via-points of one set are at least this far apart in bearing
MIN_TURN_SEP = 15.0        # out-and-back turnarounds (and petal centres) at least this far apart in bearing
PETAL_RADII = (0.5, 0.65, 0.8, 0.95)   # DEM search radii for petal centres, x the reach (no centre beyond it)


def _bsep(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _perimeter(polar):
    xy = [(d * math.sin(math.radians(t)), d * math.cos(math.radians(t))) for t, d in polar]
    pts = [(0.0, 0.0), *xy, (0.0, 0.0)]
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in itertools.pairwise(pts))


def _petal_polar(theta, dist, rho=PETAL_RHO, spread=PETAL_SPREAD):
    return [(theta - spread, rho * dist), (theta, dist), (theta + spread, rho * dist)]


def _petal_path(t):
    """(rho, spread) along the lever path, t in [0, 2]: spread 35 -> SPREAD_MIN at rho 0.75, then rho 0.75 -> RHO_MIN."""
    if t <= 1:
        return PETAL_RHO, PETAL_SPREAD + t * (SPREAD_MIN - PETAL_SPREAD)
    return PETAL_RHO + (t - 1) * (RHO_MIN - PETAL_RHO), SPREAD_MIN


_PATH_GRID = [i / 100 for i in range(201)]


def _petal_fit(perim, centre):
    """(rho, spread, k) for a DEM-centred petal of crow-flies perimeter `perim`. The spread narrows first, then
    rho, and the centre distance scales (k) only beyond either end of that path; the perimeter along the path is
    non-increasing up to the point where the petal is a thin stem, so the nearest grid point is the answer."""
    per = [centre * _perimeter(_petal_polar(0.0, 1.0, *_petal_path(t))) for t in _PATH_GRID]
    if perim >= per[0]:
        return (*_petal_path(0.0), perim / per[0])
    tmin = min(range(len(per)), key=per.__getitem__)
    if perim <= per[tmin]:
        return (*_petal_path(_PATH_GRID[tmin]), perim / per[tmin])
    i = min(range(tmin + 1), key=lambda i: abs(per[i] - perim))
    return (*_petal_path(_PATH_GRID[i]), 1.0)


PERIMETER_MIN = _perimeter(_petal_polar(0.0, 1.0, *_petal_path(2.0)))   # thinnest petal, x centre distance


def _petal_d(target_m):
    """Centre-via distance whose full-spread crow-flies petal perimeter is target / ROAD_RATIO."""
    return target_m / ROAD_RATIO / _perimeter(_petal_polar(0.0, 1.0))


def _petal_reach(target_m):
    """Farthest DEM centre a petal of this length can reach (thinnest shape, empirical road ratio)."""
    return target_m / ROAD_RATIO / PERIMETER_MIN


def _petal_state(theta, target_m, centre_dist=None, score=None):
    """Petal fanned around heading theta. Flow petals: centre at d, the whole set scaled with the radius. DEM
    petals (centre_dist given): the centre stays on the DEM point and the sides absorb the length (see _petal_fit)."""
    d = _petal_d(target_m)
    if centre_dist is not None:     # DEM centre: stays on the point; the sides absorb the length first
        return _State(theta % 360, target_m / ROAD_RATIO, shape="petal", lever=True, centre=centre_dist,
                      param0=d, scores=[score])
    polar = _petal_polar(theta, d)
    return _State(theta % 360, d, polar=polar, param0=d, shape="petal",
                  scores=[] if score is None else [score])


def _objective_states(objective, mode, dem, start, d0, bearings, region, res, target_m):
    """DEM-driven states for 'climb' / 'flat', or None (with a note) when the DEM cannot support them."""
    dem = dem if dem is not None else Dem()
    fn = climb_via_points if objective == "climb" else flat_via_points
    vp = fn(dem, start, d0, region=region)
    if vp.coverage_note:
        res.notes.append(vp.coverage_note)
    if len(vp) < MIN_OBJECTIVE_POINTS:
        res.notes.append(f"{objective}: DEM covers only {len(vp)} candidate points (<{MIN_OBJECTIVE_POINTS}); "
                         "using evenly spaced headings")
        return None
    states = []
    if mode == "out-and-back":
        chosen = []
        for p in vp:
            if all(_bsep(p.heading_deg, q.heading_deg) >= MIN_TURN_SEP for q in chosen):
                chosen.append(p)
            if len(chosen) == bearings:
                break
        for p in chosen:
            states.append(_State(p.heading_deg, p.radius_m, polar=[(p.heading_deg, p.radius_m)],
                                 param0=p.radius_m, scores=[p.score]))
    else:
        triples = []
        for tri in itertools.combinations(vp, 3):
            if all(_bsep(a.heading_deg, b.heading_deg) >= MIN_BEARING_SEP for a, b in itertools.combinations(tri, 2)):
                triples.append((sum(p.score for p in tri), tri))
        triples.sort(key=lambda x: -x[0])
        picked = []
        for _, tri in triples:
            ids = {id(p) for p in tri}
            if any(len(ids & {id(p) for p in t}) >= 2 for t in picked):
                continue
            picked.append(tri)
            if len(picked) == bearings:
                break
        for tri in picked:
            best = max(tri, key=lambda p: p.score)
            tri = sorted(tri, key=lambda p: p.heading_deg)
            polar = [(p.heading_deg, p.radius_m) for p in tri]
            k0 = target_m / _perimeter(polar)   # initial radial scale: crow-flies perimeter ~ target length
            states.append(_State(best.heading_deg, d0 * k0, polar=polar, param0=d0, scores=[p.score for p in tri]))
    if mode == "loop":
        vp2 = fn(dem, start, _petal_reach(target_m), radii=PETAL_RADII, region=region)
        chosen = []
        for p in vp2:
            if all(_bsep(p.heading_deg, q.heading_deg) >= MIN_TURN_SEP for q in chosen):
                chosen.append(p)
            if len(chosen) == max(1, bearings // 2):
                break
        states += [_petal_state(p.heading_deg, target_m, p.radius_m, p.score) for p in chosen]
    if not states:
        res.notes.append(f"{objective}: no usable via-point set found; using evenly spaced headings")
        return None
    return states


def _one_way(client, res, start, end, variants, alts, max_calls, region, lo, hi):
    if end is None:
        raise ValueError("one-way needs an end point")
    res.notes.append(f"one-way: length range {lo:g}-{hi:g} km is not enforced (routes follow the start/end pair)")
    if len(variants) * len(alts) > max_calls:
        keep_v = max(1, max_calls // len(alts))
        variants = variants[:keep_v]
        res.notes.append(f"call budget max_calls={max_calls} limits one-way to {len(variants)} variant(s)")
    kept, dropped, skipped = generate(client, start, end, variants=variants, alts=alts, region=region)
    res.calls = len(variants) * len(alts) if tuple(start) != tuple(float(x) for x in end) else 0
    for c in kept + dropped:
        c.plan = {"mode": "one-way", "iterations": 1, "length_km": round(c.length_m / 1000, 3)}
    res.kept, res.dropped, res.skipped = kept, dropped, skipped
    return res
