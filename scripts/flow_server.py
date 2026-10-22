"""Flow route planner API. Run: uv run scripts/flow_server.py [--region ireland] [--port 8081]
[--brouter http://localhost:17777]"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from flowplan import stop_model
from flowplan.brouter import (
    DEFAULT_URL,
    BRouterClient,
    BRouterUnavailable,
    cycle_km,
    validate_params,
)
from flowplan.candidates import DEFAULT_VARIANTS, Variant, generate, lanes_variant
from flowplan.explain import explain
from flowplan.plan import plan_candidates
from flowplan.ranking import DEFAULT_TURN_WEIGHT, OBJECTIVES, rank, score_candidate
from flowplan.scoring import FlowIndex
from flowplan.terrain import Dem

log = logging.getLogger("flow_server")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
BBOX = {"ireland": {"lon_min": -10.7, "lon_max": -5.4, "lat_min": 51.3, "lat_max": 55.5}}


def parse_latlon(s: str, name: str, bbox: dict) -> tuple[float, float]:
    """Parse 'lat,lon' -> (lon, lat); 400 on garbage or outside bbox."""
    try:
        lat_s, lon_s = s.split(",")
        lat, lon = float(lat_s), float(lon_s)
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ValueError
    except ValueError:
        raise HTTPException(400, f"'{name}' must be 'lat,lon' (got {s!r})") from None
    if not (bbox["lat_min"] <= lat <= bbox["lat_max"] and bbox["lon_min"] <= lon <= bbox["lon_max"]):
        raise HTTPException(
            400, f"'{name}' ({lat},{lon}) is outside the supported region "
                 f"(lon {bbox['lon_min']}..{bbox['lon_max']}, lat {bbox['lat_min']}..{bbox['lat_max']})")
    return lon, lat


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


def parse_float(s: str, name: str) -> float:
    try:
        f = float(s)
    except (TypeError, ValueError):
        raise HTTPException(400, f"'{name}' must be a number (got {s!r})") from None
    if not math.isfinite(f):
        raise HTTPException(400, f"'{name}' must be finite (got {s!r})")
    return f


def parse_scales(s: str) -> tuple:
    """'0.5,1,2' -> (0.5, 1.0, 2.0); each validated with the brouter flow_scale rule."""
    out = []
    for part in s.split(","):
        part = part.strip()
        try:
            f = float(part)
            validate_params({"flow_scale": f})
        except ValueError as e:
            raise HTTPException(400, f"'scales': {e}") from None
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


def create_app(region: str = "ireland", brouter_url: str = DEFAULT_URL, client=None,
               index=None, model=None, model_path=None, dem=None) -> FastAPI:
    app = FastAPI(title="flow planner")
    bbox = BBOX[region]
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
    client = client or BRouterClient(brouter_url)
    dem = dem if dem is not None else Dem()
    try:
        if not client.health():
            log.warning("BRouter not healthy at %s; start it with `scripts/run_brouter.sh serve`",
                        brouter_url)
    except Exception as e:  # noqa: BLE001 - never exit on startup
        log.warning("BRouter health check failed: %s", e)

    @app.get("/api/health")
    def health():
        return {"brouter": client.health(), "region": region, "index_rows": len(index),
                "weight_set": model.weight_set, "bbox": bbox}

    cache = CandidateCache()

    def named_model(name: str, param: str):
        if name not in sets:
            raise HTTPException(400, f"'{param}' must be one of "
                                     f"{', '.join(model_json['weight_sets'])} (got {name!r})")
        return sets[name]

    @app.get("/api/model")
    def model_info():
        sets = {name: {c: {k: v.get(k) for k in ("p", "p_lo", "p_hi", "mean_stop_s", "note")}
                       for c, v in ws.items()}
                for name, ws in model_json["weight_sets"].items()}
        return {"default_weight_set": model_json["default_weight_set"],
                "precedence": model_json["precedence"], "weight_sets": sets,
                "midway_background_p": model_json.get("midway_background_p", 0.0)}

    def resolve_settings(qp):
        """Parse and validate the model/routing/ranking settings shared by /api/route and /api/plan."""
        get = qp.get
        router = get("router") or "base"
        if router not in ("base", "table"):
            raise HTTPException(400, f"'router' must be base or table (got {router!r})")
        weights, blend_with, blend = get("weights"), get("blend_with"), get("blend")
        m = named_model(weights, "weights") if weights else model
        base_model = m
        blend_alpha = None
        if blend_with is not None or blend is not None:
            if blend_with is None or blend is None:
                raise HTTPException(400, "'blend_with' and 'blend' must be given together")
            blend_alpha = parse_float(blend, "blend")
            if not 0.0 <= blend_alpha <= 1.0:
                raise HTTPException(400, f"'blend' must be within 0..1 (got {blend!r})")
            m = stop_model.blend(m, named_model(blend_with, "blend_with"), blend_alpha)
        overrides = {}
        for c in OVERRIDE_CAUSES:
            raw = get(f"p_{c}")
            if raw is not None:
                v = parse_float(raw, f"p_{c}")
                if not 0.0 <= v <= 1.0:
                    raise HTTPException(400, f"'p_{c}' must be within 0..1 (got {raw!r})")
                overrides[c] = v
        if overrides:
            try:
                m = m.with_overrides(overrides)
            except (KeyError, ValueError) as e:
                raise HTTPException(400, str(e.args[0])) from None
        guard, turn_weight = get("guard"), get("turn_weight")
        guard_v = 1.3 if guard is None else parse_float(guard, "guard")
        if not 0.0 <= guard_v <= MAX_GUARD:
            raise HTTPException(400, f"'guard' must be within 0..{MAX_GUARD} (got {guard!r})")
        tw = DEFAULT_TURN_WEIGHT if turn_weight is None else parse_float(turn_weight, "turn_weight")
        if not 0.0 <= tw <= MAX_TURN_WEIGHT:
            raise HTTPException(400, f"'turn_weight' must be within 0..{MAX_TURN_WEIGHT:g} (got {turn_weight!r})")
        scales = get("scales")
        scales_t = DEFAULT_SCALES if scales is None else parse_scales(scales)
        straight = {}
        for name in ("lane_bonus", "turn_cost", "lane_exit_cost", "cycleway_base"):
            raw = get(name)
            v = STRAIGHT_DEFAULTS[name] if raw is None else parse_float(raw, name)
            try:
                validate_params({name: v})
            except ValueError as e:
                raise HTTPException(400, f"'{name}': {e}") from None
            straight[name] = v
        costs = (base_model if router == "base" else m).brouter_costs()
        profile_params = dict(costs)
        # emq.27: always sent explicitly (flow variants only; generate() leaves fastbike untouched), so the
        # server defaults and the profile defaults cannot drift apart silently
        profile_params.update(straight)
        for ck, cv in costs.items():
            if not math.isfinite(cv) or not 0 <= cv <= 1000:
                raise HTTPException(400, f"derived {ck}={cv} is outside 0..1000")
        return SimpleNamespace(
            m=m, weights=weights, blend_with=blend_with, blend_alpha=blend_alpha, overrides=overrides,
            guard=guard_v, tw=tw, scales=scales_t, straight=straight, router=router, costs=costs,
            profile_params=profile_params,
            refresh=get("refresh") not in (None, "", "0", "false"),
            lanes=get("lanes_variant") not in (None, "", "0", "false"),
            debug=get("debug") not in (None, "", "0", "false"))

    def variants_of(st):
        variants = variants_for(st.scales)
        if st.lanes:
            variants = (*variants, lanes_variant(st.straight["lane_bonus"]))
        return variants

    def route_dict(s, debug_b):
        c, sc, x = s.cand, s.score, s.extra
        r = {
            "rank": s.rank, "id": c.key, "variant": c.variant, "profile": c.profile,
            "alt": c.alt,
            "geometry": {"type": "LineString", "coordinates": [list(p) for p in c.geometry]},
            "stats": {"distance_km": c.length_m / 1000, "ascent_m": x["ascent_m"],
                      "descent_m": x["descent_m"], "climbs": x["climbs"],
                      "climb_score": x["climb_score"], "hardest_climb": x["hardest_climb"],
                      "brouter_time_s": c.time_s, "expected_stops": sc.expected_stops,
                      "stops_per_km": sc.stops_per_km, "expected_stop_s": sc.expected_stop_s,
                      "by_class": sc.by_class,
                      "cycle_km": cycle_km(c.segments),
                      "turns": sc.turns, "turns_per_km": sc.turns_per_km,
                      "sharp_turns": sc.sharp_turns,
                      "longest_straight_km": sc.longest_straight_km,
                      "mean_straight_km": sc.mean_straight_km},
            "delta_vs_fastest": s.delta_vs_fastest,
            "hits": [{"lat": h["lat"], "lon": h["lon"], "cause": h["cause"], "p": h["p"]}
                     for h in sc.hits],
        }
        if c.plan is not None:
            r["plan"] = c.plan
        if debug_b:
            r.update(explain(c.segments, sc.hits, c.cost))
            r["turn_points"] = sc.turn_points
        return r

    def settings_echo(st, n):
        return {"weights": st.weights or model.weight_set, "blend_with": st.blend_with,
                "blend": st.blend_alpha, "overrides": st.overrides, "guard": st.guard,
                "scales": list(st.scales), "n": n, "router": st.router,
                "brouter_costs": st.costs, "lane_bonus": st.straight["lane_bonus"],
                "turn_cost": st.straight["turn_cost"],
                "lane_exit_cost": st.straight["lane_exit_cost"],
                "cycleway_base": st.straight["cycleway_base"],
                "lanes_variant": st.lanes, "turn_weight": st.tw}

    def finish(st, kept, dropped, skipped, hit, brouter_ms, t0, t1, n, top_fn, query, extra=None):
        """Score kept candidates, rank via top_fn(scored), build the response shared by route and plan."""
        scored = [score_candidate(c, st.m, index, region) for c in kept]
        t2 = time.perf_counter()
        top = top_fn(scored)
        out = {"query": query, "weight_set": st.m.weight_set,
               "routes": [route_dict(s, st.debug) for s in top],
               "settings": settings_echo(st, n),
               "model": {c: st.m.p(c) for c in st.m.classes}, "cached": hit,
               "candidates_total": len(kept) + len(dropped),
               "candidates_deduped": len(kept), "skipped": skipped,
               "timings_ms": {"brouter": 0 if hit else brouter_ms,
                              "score": round((t2 - t1) * 1000),
                              "total": round((time.perf_counter() - t0) * 1000)}}
        out.update(extra or {})
        return out

    def log_skipped(skipped):
        for sk in skipped:
            log.warning("BRouter request skipped: variant=%s alt=%s error=%s",
                        sk["variant"], sk["alt"], sk["error"])

    @app.get("/api/route")
    def route(request: Request, from_: str = Query(alias="from"), to: str = Query(), n: int = 4):
        t0 = time.perf_counter()
        start = parse_latlon(from_, "from", bbox)
        end = parse_latlon(to, "to", bbox)
        n = max(1, min(6, n))
        st = resolve_settings(request.query_params)
        key = (round(start[1], 5), round(start[0], 5), round(end[1], 5), round(end[0], 5),
               st.scales, tuple(sorted(st.costs.items())), tuple(sorted(st.straight.items())), st.lanes)
        hit = None if st.refresh else cache.get(key)
        if hit is not None:
            kept, dropped, skipped, brouter_ms = hit
        else:
            try:
                kept, dropped, skipped = generate(client, start, end, variants=variants_of(st),
                                                  region=region, profile_params=st.profile_params)
            except BRouterUnavailable as e:
                raise HTTPException(503, str(e)) from None
            brouter_ms = round((time.perf_counter() - t0) * 1000)
            if kept:
                cache.put(key, (kept, dropped, skipped, brouter_ms))
        t1 = time.perf_counter()
        if hit is None:
            log_skipped(skipped)
        if not kept:
            detail = "no route found"
            if skipped:
                detail += ": " + "; ".join(sorted({s["error"] for s in skipped}))
            raise HTTPException(404, detail)
        return finish(st, kept, dropped, skipped, hit is not None, brouter_ms, t0, t1, n,
                      lambda sc: rank(sc, n=n, guard=st.guard, turn_weight=st.tw),
                      {"from": {"lat": start[1], "lon": start[0]},
                       "to": {"lat": end[1], "lon": end[0]}, "n": n})

    def int_param(qp, name, default, lo, hi):
        raw = qp.get(name)
        if raw is None or raw == "":
            return default
        try:
            v = int(raw)
        except ValueError:
            raise HTTPException(400, f"'{name}' must be an integer (got {raw!r})") from None
        if not lo <= v <= hi:
            raise HTTPException(400, f"'{name}' must be within {lo}..{hi} (got {raw!r})")
        return v

    def km_param(qp, name):
        raw = qp.get(name)
        if raw is None or raw == "":
            return None
        v = parse_float(raw, name)
        if not 0 < v <= MAX_PLAN_KM:
            raise HTTPException(400, f"'{name}' must be within 0..{MAX_PLAN_KM:g} km (got {raw!r})")
        return v

    @app.get("/api/plan")
    def plan(request: Request):
        t0 = time.perf_counter()
        qp = request.query_params
        mode_raw = qp.get("mode") or "loop"
        mode_api = mode_raw.strip().lower().replace("-", "_")
        if mode_api not in PLAN_MODES:
            raise HTTPException(400, f"'mode' must be loop, out_and_back or one_way (got {mode_raw!r})")
        mode = mode_api.replace("_", "-")
        if not qp.get("from"):
            raise HTTPException(400, "'from' is required (lat,lon)")
        start = parse_latlon(qp["from"], "from", bbox)
        end = parse_latlon(qp["to"], "to", bbox) if qp.get("to") else None
        if mode == "one-way" and end is None:
            raise HTTPException(400, "'to' is required for mode=one_way")
        objective = qp.get("objective") or "flow"
        if objective not in OBJECTIVES:
            raise HTTPException(400, f"'objective' must be flow, climb or flat (got {objective!r})")
        return_mode = qp.get("return") or "same"
        if return_mode not in ("same", "free"):
            raise HTTPException(400, f"'return' must be same or free (got {return_mode!r})")
        n = int_param(qp, "n", 4, 1, 6)
        bearings = int_param(qp, "bearings", 8, 3, 12)
        max_calls = int_param(qp, "max_calls", 48, 1, MAX_PLAN_CALLS)
        length, kmin, kmax = km_param(qp, "length_km"), km_param(qp, "min_km"), km_param(qp, "max_km")
        if length is not None and (kmin is not None or kmax is not None):
            raise HTTPException(400, "give either 'length_km' or 'min_km'/'max_km', not both")
        if (kmin is None) != (kmax is None):
            raise HTTPException(400, "'min_km' and 'max_km' must be given together")
        if length is not None:
            kmin, kmax = length * 0.9, length * 1.1
        if kmin is not None and kmin > kmax:
            raise HTTPException(400, f"'min_km' must be <= 'max_km' (got {kmin:g} > {kmax:g})")
        fixed_end = mode == "out-and-back" and end is not None
        if kmin is None and mode == "loop" or (kmin is None and mode == "out-and-back" and end is None):
            raise HTTPException(400, "'length_km' (or 'min_km' and 'max_km') is required for "
                                     f"mode={mode_api}")
        st = resolve_settings(qp)
        enforce = mode != "one-way" and not fixed_end and kmin is not None
        lrange = (round(kmin, 4), round(kmax, 4)) if kmin is not None else None
        key = ("plan", mode, round(start[1], 5), round(start[0], 5),
               None if end is None else (round(end[1], 5), round(end[0], 5)), lrange, bearings,
               objective, return_mode, max_calls, st.scales, tuple(sorted(st.costs.items())),
               tuple(sorted(st.straight.items())), st.lanes)
        hit = None if st.refresh else cache.get(key)
        if hit is not None:
            kept, dropped, skipped, brouter_ms, calls, notes = hit
        else:
            try:
                res = plan_candidates(client, mode, start, end, length_km=lrange or (1.0, MAX_PLAN_KM),
                                      bearings=bearings, variants=variants_of(st), max_calls=max_calls,
                                      profile_params=st.profile_params, region=region,
                                      return_mode=return_mode, objective=objective, dem=dem)
            except BRouterUnavailable as e:
                raise HTTPException(503, str(e)) from None
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
            kept, dropped, skipped, calls, notes = res.kept, res.dropped, res.skipped, res.calls, res.notes
            brouter_ms = round((time.perf_counter() - t0) * 1000)
            if kept:
                cache.put(key, (kept, dropped, skipped, brouter_ms, calls, notes))
        t1 = time.perf_counter()
        if hit is None:
            log_skipped(skipped)
        notes = list(notes)
        if mode == "loop" and end is not None:
            notes.append("'to' is ignored for loops")
        if not kept:
            detail = "no route found"
            if notes:
                detail += ": " + "; ".join(notes)
            if skipped:
                detail += "; " + "; ".join(sorted({s["error"] for s in skipped}))
            raise HTTPException(404, detail)
        block = {"mode": mode_api, "objective": objective, "return": return_mode,
                 "length_range": list(lrange) if lrange and mode != "one-way" else None,
                 "calls": calls, "notes": notes}
        query = {"mode": mode_api, "from": {"lat": start[1], "lon": start[0]}, "n": n,
                 "to": None if end is None else {"lat": end[1], "lon": end[0]},
                 "bearings": bearings, "max_calls": max_calls}
        return finish(st, kept, dropped, skipped, hit is not None, brouter_ms, t0, t1, n,
                      lambda sc: rank(sc, n=n, guard=st.guard, turn_weight=st.tw, objective=objective,
                                      length_range=lrange if enforce else None),
                      query, {"plan": block})

    # API routes first; the static mount is a catch-all
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


def main():
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="ireland", choices=sorted(BBOX))
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--brouter", default=DEFAULT_URL)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(a.region, a.brouter), host="127.0.0.1", port=a.port)


if __name__ == "__main__":
    main()
