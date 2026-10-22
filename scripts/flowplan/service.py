"""Planner service shared by the FastAPI server and the MCP: settings parsing, /route and /plan logic,
candidate cache, route dicts and the per-route explain summary. Raises ServiceError(status, detail)."""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

from . import stop_model
from .brouter import (
    DEFAULT_URL,
    BRouterClient,
    BRouterUnavailable,
    cycle_km,
    validate_params,
)
from .candidates import DEFAULT_VARIANTS, Variant, generate, lanes_variant
from .explain import explain, ride_warnings
from .plan import plan_candidates
from .ranking import (
    DEFAULT_DIVERSITY,
    DEFAULT_TURN_WEIGHT,
    ELEVATION_SOURCES,
    OBJECTIVES,
    rank,
    score_candidate,
)
from .scoring import FlowIndex
from .terrain import Dem

log = logging.getLogger("flowplan.service")
BBOX = {"ireland": {"lon_min": -10.7, "lon_max": -5.4, "lat_min": 51.3, "lat_max": 55.5}}
DEFAULT_SCALES = (0.5, 1.0, 2.0)
MAX_GUARD = 3.0
MAX_TURN_WEIGHT = 2.0
# emq.27 'Straight & lanes' defaults; equal to the profiles/flow.brf globals. Applied to flow variants only.
STRAIGHT_DEFAULTS = {"lane_bonus": 0.7, "turn_cost": 400.0, "lane_exit_cost": 150.0, "cycleway_base": 1.0}
CACHE_SIZE = 32
PLAN_MODES = ("loop", "out_and_back", "one_way")
MAX_PLAN_CALLS = 96
MAX_PLAN_KM = 1000.0
OVERRIDE_CAUSES = ("signal", "stop", "give_way", "rb_entry", "xing_signal", "yield_infer",
                   "yield_equal")


class ServiceError(Exception):
    """A user-facing planner error; status follows HTTP semantics (400 bad input, 404 none found, 503 BRouter)."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def parse_latlon(s: str, name: str, bbox: dict) -> tuple[float, float]:
    """Parse 'lat,lon' -> (lon, lat); 400 on garbage or outside bbox."""
    try:
        lat_s, lon_s = s.split(",")
        lat, lon = float(lat_s), float(lon_s)
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ValueError
    except ValueError:
        raise ServiceError(400, f"'{name}' must be 'lat,lon' (got {s!r})") from None
    if not (bbox["lat_min"] <= lat <= bbox["lat_max"] and bbox["lon_min"] <= lon <= bbox["lon_max"]):
        raise ServiceError(
            400, f"'{name}' ({lat},{lon}) is outside the supported region "
                 f"(lon {bbox['lon_min']}..{bbox['lon_max']}, lat {bbox['lat_min']}..{bbox['lat_max']})")
    return lon, lat


def parse_float(s: str, name: str) -> float:
    try:
        f = float(s)
    except (TypeError, ValueError):
        raise ServiceError(400, f"'{name}' must be a number (got {s!r})") from None
    if not math.isfinite(f):
        raise ServiceError(400, f"'{name}' must be finite (got {s!r})")
    return f


def parse_scales(s: str) -> tuple:
    """'0.5,1,2' -> (0.5, 1.0, 2.0); each validated with the brouter flow_scale rule."""
    out = []
    for part in s.split(","):
        part = part.strip()
        try:
            f = float(part)
            validate_params({"flow_scale": f})
            if f <= 0:  # 0 is reserved for the fixed Fastest baseline variant
                raise ValueError(f"flow_scale must be > 0 for 'scales', got {part!r}")
        except ValueError as e:
            raise ServiceError(400, f"'scales': {e}") from None
        if f not in out:
            out.append(f)
    return tuple(out)


def variants_for(scales: tuple) -> tuple:
    if scales == DEFAULT_SCALES:
        return DEFAULT_VARIANTS
    fast = next(v for v in DEFAULT_VARIANTS if v.name == "fastbike")
    names = {0.5: "flow_lo", 1.0: "flow", 2.0: "flow_hi"}
    return (fast, *(Variant(names.get(f, f"flow_{f:g}"), "flow", {"flow_scale": f})
                    for f in scales))


class CandidateCache:
    """Small thread-safe LRU of generated candidates."""

    def __init__(self, size: int = CACHE_SIZE):
        self.size, self._d, self._lock = size, OrderedDict(), threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
        return None

    def put(self, key, value):
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.size:
                self._d.popitem(last=False)


def int_param(qp, name, default, lo, hi):
    raw = qp.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except ValueError:
        raise ServiceError(400, f"'{name}' must be an integer (got {raw!r})") from None
    if not lo <= v <= hi:
        raise ServiceError(400, f"'{name}' must be within {lo}..{hi} (got {raw!r})")
    return v


def km_param(qp, name):
    raw = qp.get(name)
    if raw is None or raw == "":
        return None
    v = parse_float(raw, name)
    if not 0 < v <= MAX_PLAN_KM:
        raise ServiceError(400, f"'{name}' must be within 0..{MAX_PLAN_KM:g} km (got {raw!r})")
    return v


def route_dict(s, debug_b=False):
    c, sc, x = s.cand, s.score, s.extra
    r = {
        "rank": s.rank, "id": c.route_id, "variant": c.variant, "profile": c.profile,
        "alt": c.alt,
        "geometry": {"type": "LineString", "coordinates": [list(p) for p in c.geometry]},
        "stats": {"distance_km": c.length_m / 1000, "ascent_m": x["ascent_m"],
                  "descent_m": x["descent_m"], "climbs": x["climbs"],
                  "climb_score": x["climb_score"], "hardest_climb": x["hardest_climb"],
                  "elevation_source": x["elevation_source"],
                  "brouter_time_s": c.time_s, "expected_stops": sc.expected_stops,
                  "stops_per_km": sc.stops_per_km, "expected_stop_s": sc.expected_stop_s,
                  "by_class": sc.by_class,
                  "cycle_km": cycle_km(c.segments),
                  "turns": sc.turns, "turns_per_km": sc.turns_per_km,
                  "sharp_turns": sc.sharp_turns,
                  "longest_straight_km": sc.longest_straight_km,
                  "mean_straight_km": sc.mean_straight_km},
        "delta_vs_fastest": s.delta_vs_fastest,
        "warnings": ride_warnings(c.segments),
        "hits": [{"lat": h["lat"], "lon": h["lon"], "cause": h["cause"], "p": h["p"]}
                 for h in sc.hits],
    }
    if c.duplicate_of:
        r["duplicate_of"] = c.duplicate_of
    if c.plan is not None:
        r["plan"] = c.plan
    if c.elevations and any(e is not None for e in c.elevations):
        # parallel to geometry; the profile that climb stats used (stats.elevation_source); the UI GPX writes it
        r["elevations"] = [None if e is None else round(e, 1) for e in c.elevations]
    if debug_b:
        r.update(explain(c.segments, sc.hits, c.cost))
        r["turn_points"] = sc.turn_points
    return r


class PlannerService:
    def __init__(self, client, index, model, sets, dem, region="ireland", model_json=None):
        self.client, self.index, self.model, self.sets, self.dem = client, index, model, sets, dem
        self.region, self.bbox = region, BBOX[region]
        self.model_json = model_json or {"weight_sets": {n: None for n in sets}}
        self.cache = CandidateCache()

    @classmethod
    def create(cls, region="ireland", brouter_url=DEFAULT_URL, client=None, index=None, model=None,
               model_path=None, dem=None):
        model_path = Path(model_path) if model_path else stop_model.DEFAULT_PATH
        with open(model_path) as f:
            model_json = json.load(f)
        # all weight sets loaded once at startup
        sets = {name: stop_model.load(model_path, name) for name in model_json["weight_sets"]}
        model = model or stop_model.load(model_path)
        log.info("stop model weight_set=%s", model.weight_set)
        if index is None:
            index = FlowIndex.load(region)
        log.info("flow index %s: %d rows, load_seconds=%.2f", region, len(index), index.load_seconds)
        return cls(client or BRouterClient(brouter_url), index, model, sets,
                   dem if dem is not None else Dem(), region, model_json)

    # ---- info ----
    def health(self):
        return {"brouter": self.client.health(), "region": self.region, "index_rows": len(self.index),
                "weight_set": self.model.weight_set, "bbox": self.bbox}

    def model_info(self):
        mj = self.model_json
        sets = {name: {c: {k: v.get(k) for k in ("p", "p_lo", "p_hi", "mean_stop_s", "note")}
                       for c, v in ws.items()}
                for name, ws in mj["weight_sets"].items()}
        return {"default_weight_set": mj["default_weight_set"],
                "precedence": mj["precedence"], "weight_sets": sets,
                "midway_background_p": mj.get("midway_background_p", 0.0)}

    # ---- settings ----
    def named_model(self, name: str, param: str):
        if name not in self.sets:
            raise ServiceError(400, f"'{param}' must be one of "
                                    f"{', '.join(self.model_json['weight_sets'])} (got {name!r})")
        return self.sets[name]

    def resolve_settings(self, qp):
        """Parse and validate the model/routing/ranking settings shared by route and plan.
        qp: mapping of str -> str (query params)."""
        get = qp.get
        router = get("router") or "base"
        if router not in ("base", "table"):
            raise ServiceError(400, f"'router' must be base or table (got {router!r})")
        weights, blend_with, blend = get("weights"), get("blend_with"), get("blend")
        m = self.named_model(weights, "weights") if weights else self.model
        base_model = m
        blend_alpha = None
        if blend_with is not None or blend is not None:
            if blend_with is None or blend is None:
                raise ServiceError(400, "'blend_with' and 'blend' must be given together")
            blend_alpha = parse_float(blend, "blend")
            if not 0.0 <= blend_alpha <= 1.0:
                raise ServiceError(400, f"'blend' must be within 0..1 (got {blend!r})")
            m = stop_model.blend(m, self.named_model(blend_with, "blend_with"), blend_alpha)
        overrides = {}
        for c in OVERRIDE_CAUSES:
            raw = get(f"p_{c}")
            if raw is not None:
                v = parse_float(raw, f"p_{c}")
                if not 0.0 <= v <= 1.0:
                    raise ServiceError(400, f"'p_{c}' must be within 0..1 (got {raw!r})")
                overrides[c] = v
        if overrides:
            try:
                m = m.with_overrides(overrides)
            except (KeyError, ValueError) as e:
                raise ServiceError(400, str(e.args[0])) from None
        guard, turn_weight = get("guard"), get("turn_weight")
        guard_v = 1.3 if guard is None else parse_float(guard, "guard")
        if not 0.0 <= guard_v <= MAX_GUARD:
            raise ServiceError(400, f"'guard' must be within 0..{MAX_GUARD} (got {guard!r})")
        tw = DEFAULT_TURN_WEIGHT if turn_weight is None else parse_float(turn_weight, "turn_weight")
        if not 0.0 <= tw <= MAX_TURN_WEIGHT:
            raise ServiceError(400, f"'turn_weight' must be within 0..{MAX_TURN_WEIGHT:g} (got {turn_weight!r})")
        div_raw = get("diversity")
        div = DEFAULT_DIVERSITY if div_raw is None else parse_float(div_raw, "diversity")
        if not 0.0 <= div <= 1.0:
            raise ServiceError(400, f"'diversity' must be within 0..1 (got {div_raw!r})")
        elevation_source = get("elevation_source") or "auto"
        if elevation_source not in ELEVATION_SOURCES:
            raise ServiceError(400, f"'elevation_source' must be one of {', '.join(ELEVATION_SOURCES)} "
                                    f"(got {elevation_source!r})")
        scales = get("scales")
        scales_t = DEFAULT_SCALES if scales is None else parse_scales(scales)
        straight = {}
        for name in ("lane_bonus", "turn_cost", "lane_exit_cost", "cycleway_base"):
            raw = get(name)
            v = STRAIGHT_DEFAULTS[name] if raw is None else parse_float(raw, name)
            try:
                validate_params({name: v})
            except ValueError as e:
                raise ServiceError(400, f"'{name}': {e}") from None
            straight[name] = v
        costs = (base_model if router == "base" else m).brouter_costs()
        profile_params = dict(costs)
        # emq.27: always sent explicitly (the baseline variant overrides them with its own fixed params), so the
        # server defaults and the profile defaults cannot drift apart silently
        profile_params.update(straight)
        for ck, cv in costs.items():
            if not math.isfinite(cv) or not 0 <= cv <= 1000:
                raise ServiceError(400, f"derived {ck}={cv} is outside 0..1000")
        return SimpleNamespace(
            m=m, weights=weights, blend_with=blend_with, blend_alpha=blend_alpha, overrides=overrides,
            guard=guard_v, tw=tw, diversity=div, elevation_source=elevation_source, scales=scales_t, straight=straight, router=router, costs=costs,
            profile_params=profile_params,
            refresh=get("refresh") not in (None, "", "0", "false"),
            lanes=get("lanes_variant") not in (None, "", "0", "false"),
            debug=get("debug") not in (None, "", "0", "false"))

    @staticmethod
    def variants_of(st):
        variants = variants_for(st.scales)
        if st.lanes:
            variants = (*variants, lanes_variant(st.straight["lane_bonus"]))
        return variants

    def settings_echo(self, st, n):
        return {"weights": st.weights or self.model.weight_set, "blend_with": st.blend_with,
                "blend": st.blend_alpha, "overrides": st.overrides, "guard": st.guard,
                "scales": list(st.scales), "n": n, "router": st.router,
                "brouter_costs": st.costs, "lane_bonus": st.straight["lane_bonus"],
                "turn_cost": st.straight["turn_cost"],
                "lane_exit_cost": st.straight["lane_exit_cost"],
                "cycleway_base": st.straight["cycleway_base"],
                "lanes_variant": st.lanes, "turn_weight": st.tw,
                "diversity": st.diversity, "elevation_source": st.elevation_source}

    def finish(self, st, kept, dropped, skipped, hit, brouter_ms, t0, t1, n, top_fn, query, extra=None):
        """Score kept candidates, rank via top_fn(scored) -> (response dict, top ScoredCandidates)."""
        scored = [score_candidate(c, st.m, self.index, self.region, st.elevation_source, self.dem) for c in kept]
        t2 = time.perf_counter()
        top = top_fn(scored)
        out = {"query": query, "weight_set": st.m.weight_set,
               "routes": [route_dict(s, st.debug) for s in top],
               "settings": self.settings_echo(st, n),
               "model": {c: st.m.p(c) for c in st.m.classes}, "cached": hit,
               "candidates_total": len(kept) + len(dropped),
               "candidates_deduped": len(kept), "skipped": skipped,
               "timings_ms": {"brouter": 0 if hit else brouter_ms,
                              "score": round((t2 - t1) * 1000),
                              "total": round((time.perf_counter() - t0) * 1000)}}
        out.update(extra or {})
        return out, top

    @staticmethod
    def log_skipped(skipped):
        for sk in skipped:
            log.warning("BRouter request skipped: variant=%s alt=%s error=%s",
                        sk["variant"], sk["alt"], sk["error"])

    # ---- route ----
    def route(self, from_: str, to: str, n: int = 4, qp=None):
        return self.route_scored(from_, to, n, qp)[0]

    def route_scored(self, from_: str, to: str, n: int = 4, qp=None):
        """-> (response dict, top ScoredCandidates)."""
        t0 = time.perf_counter()
        qp = qp if qp is not None else {}
        start = parse_latlon(from_, "from", self.bbox)
        end = parse_latlon(to, "to", self.bbox)
        n = max(1, min(6, n))
        st = self.resolve_settings(qp)
        key = (round(start[1], 5), round(start[0], 5), round(end[1], 5), round(end[0], 5),
               st.scales, tuple(sorted(st.costs.items())), tuple(sorted(st.straight.items())), st.lanes)
        hit = None if st.refresh else self.cache.get(key)
        if hit is not None:
            kept, dropped, skipped, brouter_ms = hit
        else:
            try:
                kept, dropped, skipped = generate(self.client, start, end, variants=self.variants_of(st),
                                                  region=self.region, profile_params=st.profile_params)
            except BRouterUnavailable as e:
                raise ServiceError(503, str(e)) from None
            brouter_ms = round((time.perf_counter() - t0) * 1000)
            if kept:
                self.cache.put(key, (kept, dropped, skipped, brouter_ms))
        t1 = time.perf_counter()
        if hit is None:
            self.log_skipped(skipped)
        if not kept:
            detail = "no route found"
            if skipped:
                detail += ": " + "; ".join(sorted({s["error"] for s in skipped}))
            raise ServiceError(404, detail)
        return self.finish(st, kept, dropped, skipped, hit is not None, brouter_ms, t0, t1, n,
                           lambda sc: rank(sc, n=n, guard=st.guard, turn_weight=st.tw, diversity=st.diversity,
                                           region=self.region),
                           {"from": {"lat": start[1], "lon": start[0]},
                            "to": {"lat": end[1], "lon": end[0]}, "n": n})

    # ---- plan ----
    def plan(self, qp):
        return self.plan_scored(qp)[0]

    def plan_scored(self, qp):
        """qp: mapping of str -> str with the /api/plan parameters. -> (response dict, top ScoredCandidates)."""
        t0 = time.perf_counter()
        mode_raw = qp.get("mode") or "loop"
        mode_api = mode_raw.strip().lower().replace("-", "_")
        if mode_api not in PLAN_MODES:
            raise ServiceError(400, f"'mode' must be loop, out_and_back or one_way (got {mode_raw!r})")
        mode = mode_api.replace("_", "-")
        if not qp.get("from"):
            raise ServiceError(400, "'from' is required (lat,lon)")
        start = parse_latlon(qp["from"], "from", self.bbox)
        end = parse_latlon(qp["to"], "to", self.bbox) if qp.get("to") else None
        if mode == "one-way" and end is None:
            raise ServiceError(400, "'to' is required for mode=one_way")
        objective = qp.get("objective") or "flow"
        if objective not in OBJECTIVES:
            raise ServiceError(400, f"'objective' must be flow, climb or flat (got {objective!r})")
        return_mode = qp.get("return") or "same"
        if return_mode not in ("same", "free"):
            raise ServiceError(400, f"'return' must be same or free (got {return_mode!r})")
        n = int_param(qp, "n", 4, 1, 6)
        bearings = int_param(qp, "bearings", 8, 3, 12)
        max_calls = int_param(qp, "max_calls", 48, 1, MAX_PLAN_CALLS)
        length, kmin, kmax = km_param(qp, "length_km"), km_param(qp, "min_km"), km_param(qp, "max_km")
        if length is not None and (kmin is not None or kmax is not None):
            raise ServiceError(400, "give either 'length_km' or 'min_km'/'max_km', not both")
        if (kmin is None) != (kmax is None):
            raise ServiceError(400, "'min_km' and 'max_km' must be given together")
        if length is not None:
            kmin, kmax = length * 0.9, length * 1.1
        if kmin is not None and kmin > kmax:
            raise ServiceError(400, f"'min_km' must be <= 'max_km' (got {kmin:g} > {kmax:g})")
        fixed_end = mode == "out-and-back" and end is not None
        if kmin is None and mode == "loop" or (kmin is None and mode == "out-and-back" and end is None):
            raise ServiceError(400, "'length_km' (or 'min_km' and 'max_km') is required for "
                                    f"mode={mode_api}")
        st = self.resolve_settings(qp)
        enforce = mode != "one-way" and not fixed_end and kmin is not None
        lrange = (round(kmin, 4), round(kmax, 4)) if kmin is not None else None
        key = ("plan", mode, round(start[1], 5), round(start[0], 5),
               None if end is None else (round(end[1], 5), round(end[0], 5)), lrange, bearings,
               objective, return_mode, max_calls, st.scales, tuple(sorted(st.costs.items())),
               tuple(sorted(st.straight.items())), st.lanes)
        hit = None if st.refresh else self.cache.get(key)
        if hit is not None:
            kept, dropped, skipped, brouter_ms, calls, notes = hit
        else:
            try:
                res = plan_candidates(self.client, mode, start, end,
                                      length_km=lrange or (1.0, MAX_PLAN_KM),
                                      bearings=bearings, variants=self.variants_of(st), max_calls=max_calls,
                                      profile_params=st.profile_params, region=self.region,
                                      return_mode=return_mode, objective=objective, dem=self.dem)
            except BRouterUnavailable as e:
                raise ServiceError(503, str(e)) from None
            except ValueError as e:
                raise ServiceError(400, str(e)) from None
            kept, dropped, skipped, calls, notes = res.kept, res.dropped, res.skipped, res.calls, res.notes
            brouter_ms = round((time.perf_counter() - t0) * 1000)
            if kept:
                self.cache.put(key, (kept, dropped, skipped, brouter_ms, calls, notes))
        t1 = time.perf_counter()
        if hit is None:
            self.log_skipped(skipped)
        notes = list(notes)
        if mode == "loop" and end is not None:
            notes.append("'to' is ignored for loops")
        if not kept:
            detail = "no route found"
            if notes:
                detail += ": " + "; ".join(notes)
            if skipped:
                detail += "; " + "; ".join(sorted({s["error"] for s in skipped}))
            raise ServiceError(404, detail)
        block = {"mode": mode_api, "objective": objective, "return": return_mode,
                 "length_range": list(lrange) if lrange and mode != "one-way" else None,
                 "calls": calls, "notes": notes}
        query = {"mode": mode_api, "from": {"lat": start[1], "lon": start[0]}, "n": n,
                 "to": None if end is None else {"lat": end[1], "lon": end[0]},
                 "bearings": bearings, "max_calls": max_calls}
        return self.finish(st, kept, dropped, skipped, hit is not None, brouter_ms, t0, t1, n,
                           lambda sc: rank(sc, n=n, guard=st.guard, turn_weight=st.tw, objective=objective,
                                           diversity=st.diversity, region=self.region,
                                           length_range=lrange if enforce else None),
                           query, {"plan": block})

    # ---- explain ----
    @staticmethod
    def explain(s) -> dict:
        """Summary for one ScoredCandidate: km by highway class, cycle km, stop events by cause and class,
        climbs, turn counts, plus the totals."""
        c, sc, x = s.cand, s.score, s.extra
        summ = explain(c.segments, sc.hits, c.cost)["summary"]
        by_cause: dict = {}
        for h in sc.hits:
            by_cause[h["cause"]] = by_cause.get(h["cause"], 0) + 1
        return {"id": c.route_id, "distance_km": c.length_m / 1000,
                "km_by_highway": {k: round(v, 2) for k, v in
                                  sorted(summ["km_by_highway"].items(), key=lambda kv: -kv[1])},
                "cycle_km": summ["cycle_km"], "expected_stops": sc.expected_stops,
                "stop_events": len(sc.hits), "stop_events_by_cause": by_cause,
                "expected_stops_by_class": sc.by_class,
                "turns": sc.turns, "sharp_turns": sc.sharp_turns,
                "longest_straight_km": sc.longest_straight_km,
                "ascent_m": x["ascent_m"], "descent_m": x["descent_m"],
                "climb_score": x["climb_score"], "climbs": x["climbs"],
                "elevation_source": x["elevation_source"]}
