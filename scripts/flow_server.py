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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from flowplan import stop_model
from flowplan.brouter import (
    DEFAULT_URL,
    BRouterClient,
    BRouterUnavailable,
    validate_params,
)
from flowplan.candidates import DEFAULT_VARIANTS, Variant, generate
from flowplan.ranking import ScoredCandidate, rank
from flowplan.scoring import FlowIndex, score

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
CACHE_SIZE = 32
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
               index=None, model=None, model_path=None) -> FastAPI:
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

    @app.get("/api/route")
    def route(request: Request, from_: str = Query(alias="from"), to: str = Query(), n: int = 4,
              weights: str | None = None, blend_with: str | None = None,
              blend: str | None = None, guard: str | None = None, scales: str | None = None,
              refresh: str | None = None):
        t0 = time.perf_counter()
        start = parse_latlon(from_, "from", bbox)
        end = parse_latlon(to, "to", bbox)
        n = max(1, min(6, n))
        m = named_model(weights, "weights") if weights else model
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
            raw = request.query_params.get(f"p_{c}")
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
        guard_v = 1.3 if guard is None else parse_float(guard, "guard")
        if not 0.0 <= guard_v <= MAX_GUARD:
            raise HTTPException(400, f"'guard' must be within 0..{MAX_GUARD} (got {guard!r})")
        scales_t = DEFAULT_SCALES if scales is None else parse_scales(scales)
        refresh_b = refresh not in (None, "", "0", "false")
        costs = m.brouter_costs()
        for ck, cv in costs.items():
            if not math.isfinite(cv) or not 0 <= cv <= 1000:
                raise HTTPException(400, f"derived {ck}={cv} is outside 0..1000")
        key = (round(start[1], 5), round(start[0], 5), round(end[1], 5), round(end[0], 5),
               scales_t, tuple(sorted(costs.items())))
        hit = None if refresh_b else cache.get(key)
        if hit is not None:
            kept, dropped, skipped, brouter_ms = hit
            brouter_ms = 0
        else:
            try:
                kept, dropped, skipped = generate(client, start, end,
                                                  variants=variants_for(scales_t), region=region,
                                                  profile_params=costs)
            except BRouterUnavailable as e:
                raise HTTPException(503, str(e)) from None
            brouter_ms = round((time.perf_counter() - t0) * 1000)
            if kept:
                cache.put(key, (kept, dropped, skipped, brouter_ms))
        t1 = time.perf_counter()
        for sk in ([] if hit is not None else skipped):
            log.warning("BRouter request skipped: variant=%s alt=%s error=%s",
                        sk["variant"], sk["alt"], sk["error"])
        if not kept:
            detail = "no route found"
            if skipped:
                detail += ": " + "; ".join(sorted({s["error"] for s in skipped}))
            raise HTTPException(404, detail)
        scored = [ScoredCandidate(c, score(c.geometry, m, index)) for c in kept]
        t2 = time.perf_counter()
        top = rank(scored, n=n, guard=guard_v)
        routes = []
        for s in top:
            c, sc = s.cand, s.score
            routes.append({
                "rank": s.rank, "id": c.key, "variant": c.variant, "profile": c.profile,
                "alt": c.alt,
                "geometry": {"type": "LineString", "coordinates": [list(p) for p in c.geometry]},
                "stats": {"distance_km": c.length_m / 1000, "ascent_m": c.ascent_m,
                          "brouter_time_s": c.time_s, "expected_stops": sc.expected_stops,
                          "stops_per_km": sc.stops_per_km, "expected_stop_s": sc.expected_stop_s,
                          "by_class": sc.by_class},
                "delta_vs_fastest": s.delta_vs_fastest,
                "hits": [{"lat": h["lat"], "lon": h["lon"], "cause": h["cause"], "p": h["p"]}
                         for h in sc.hits],
            })
        return {"query": {"from": {"lat": start[1], "lon": start[0]},
                          "to": {"lat": end[1], "lon": end[0]}, "n": n},
                "weight_set": m.weight_set, "routes": routes,
                "settings": {"weights": weights or model.weight_set, "blend_with": blend_with,
                             "blend": blend_alpha, "overrides": overrides, "guard": guard_v,
                             "scales": list(scales_t), "n": n, "brouter_costs": costs},
                "model": {c: m.p(c) for c in m.classes}, "cached": hit is not None,
                "candidates_total": len(kept) + len(dropped),
                "candidates_deduped": len(kept), "skipped": skipped,
                "timings_ms": {"brouter": brouter_ms if hit is None else 0,
                               "score": round((t2 - t1) * 1000),
                               "total": round((time.perf_counter() - t0) * 1000)}}

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
