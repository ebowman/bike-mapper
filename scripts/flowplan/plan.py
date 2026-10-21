"""Loop and out-and-back candidate generation targeting a length range (via-point rings, radius iteration).

LOOP: start -> v1 -> v2 -> v3 -> start, with the vias on a ring of radius r around the start at bearings
theta, theta+120, theta+240 (2-via fallback: theta, theta+180). r starts at target/(2*pi) * DETOUR (the
circle radius for the target length, inflated by the road detour factor) and is rescaled by
target/measured after each BRouter call, at most MAX_ITER calls per heading, stopping once the measured
length lies in [min, max]. OUT-AND-BACK: a turnaround at distance d = target/2 * DETOUR along theta (or the
explicit end); the same iteration. ONE-WAY: plain candidates.generate.
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
MAX_ITER = 3
LOOP_DISGUISE_OVERLAP = 0.6   # loops whose out and back legs overlap more than this are out-and-backs
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
                    bearings: int = 8, variants=DEFAULT_VARIANTS, alts=(0,), max_calls: int = 48,
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
        variants = tuple(v if v.profile == "fastbike" else Variant(v.name, v.profile, {**profile_params, **v.params})
                         for v in variants)
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
        if s.polar:
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

    def run_round(jobs):
        """jobs: [(points, variant, alt)] -> results; counts calls, truncates to the budget."""
        room = max_calls - res.calls
        if len(jobs) > room:
            if "budget" not in " ".join(res.notes):
                res.notes.append(f"call budget max_calls={max_calls} reached; results are partial")
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
        for s in states:
            build(s)
    total_factor = 2 if mode == "out-and-back" else 1

    def km_of(c):
        return c.length_m * total_factor / 1000

    # ---- iteration with the flow variant ----
    for rnd in range(MAX_ITER + 2):
        todo = [s for s in states if not s.done]
        if not todo:
            break
        results = run_round([(s.points, it_var, it_alt) for s in todo])
        if not results:
            break
        for s, (c, err) in zip(todo, results):
            if c is None:
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
            if s.fixed:
                s.done = s.ok = True
                if not lo <= s.km <= hi:
                    res.notes.append(f"explicit turnaround gives {s.km:.1f} km, outside {lo:g}-{hi:g} km")
            elif lo <= s.km <= hi:
                s.done = s.ok = True
            elif s.iters >= MAX_ITER:
                s.done, s.error = True, f"length {s.km:.1f} km outside {lo:g}-{hi:g} km after {s.iters} iterations"
            else:
                s.param *= min(2.0, max(0.5, target / max(s.km, 1e-6)))
                build(s)
        report(f"round {rnd + 1}: {sum(s.ok for s in states)}/{len(states)} headings in range")
    for s in states:
        if not s.done:
            s.done, s.error = True, "call budget exhausted"
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
        if not s.fixed and not lo <= km_of(c) <= hi:
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
                    elif not s.fixed and not lo <= cand_free.length_m / 1000 <= hi:
                        res.notes.append(f"free return length {cand_free.length_m / 1000:.1f} km outside range at "
                                         f"{s.heading:g} deg ({v.name}); using same")
                    else:
                        full, ret = cand_free, "free"
            c = full
        c.variant, c.alt = v.name, a
        plan = {"mode": mode, "heading_deg": s.heading, "via_points": [list(p) for p in s.points[1:-1]]
                if mode == "loop" else [], "iterations": s.iters, "length_km": round(c.length_m / 1000, 3),
                "n_via": s.n_via if mode == "loop" else None}
        if mode == "loop":
            plan["radius_m"] = round(s.param, 1)
        else:
            plan["turnaround"] = list(s.points[-1])
            plan["distance_m"] = round(s.param, 1)
            plan["return_mode"] = ret
        plan["objective"] = objective if s.polar else "flow"
        if s.polar:
            plan["via_scores"] = [round(x, 1) for x in s.scores]
        c.plan = plan
        cands.append(c)

    # ---- drop disguised out-and-backs, then dedupe (keys made unique per heading) ----
    if mode == "loop":
        keep = []
        for c in cands:
            a_, b_ = _split_halves(c.geometry, tf)
            ov = _overlap(a_, b_, tf)
            if ov > LOOP_DISGUISE_OVERLAP:
                c.duplicate_of = f"out-and-back ({ov:.0%} overlap)"
                res.dropped.append(c)
            else:
                keep.append(c)
        cands = keep
    names = {id(c): c.variant for c in cands}
    for c in cands:
        c.variant = f"{c.variant}@{c.plan['heading_deg']:g}"
    kept, dropped = dedupe(cands, region)
    for c in cands:
        c.variant = names[id(c)]
    res.kept, res.dropped = kept, res.dropped + dropped
    if not kept:
        res.notes.append("no candidate inside the requested length range")
    return res


MIN_OBJECTIVE_POINTS = 6   # fewer DEM-covered candidate points than this: fall back to even headings
MIN_BEARING_SEP = 60.0     # loop via-points of one set are at least this far apart in bearing
MIN_TURN_SEP = 15.0        # out-and-back turnarounds at least this far apart in bearing


def _bsep(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _perimeter(polar):
    xy = [(d * math.sin(math.radians(t)), d * math.cos(math.radians(t))) for t, d in polar]
    pts = [(0.0, 0.0), *xy, (0.0, 0.0)]
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in itertools.pairwise(pts))


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
