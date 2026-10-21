"""Flow route planner API. Run: uv run scripts/flow_server.py [--region ireland] [--port 8081]
[--brouter http://localhost:17777]"""
from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from flowplan import stop_model
from flowplan.brouter import DEFAULT_URL, BRouterClient, BRouterUnavailable
from flowplan.candidates import generate
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


def create_app(region: str = "ireland", brouter_url: str = DEFAULT_URL, client=None,
               index=None, model=None) -> FastAPI:
    app = FastAPI(title="flow planner")
    bbox = BBOX[region]
    model = model or stop_model.load()
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

    @app.get("/api/route")
    def route(from_: str = Query(alias="from"), to: str = Query(), n: int = 4):
        t0 = time.perf_counter()
        start = parse_latlon(from_, "from", bbox)
        end = parse_latlon(to, "to", bbox)
        n = max(1, min(6, n))
        try:
            kept, dropped, skipped = generate(client, start, end, region=region)
        except BRouterUnavailable as e:
            raise HTTPException(503, str(e)) from None
        t1 = time.perf_counter()
        if not kept:
            detail = "no route found"
            if skipped:
                detail += ": " + "; ".join(sorted({s["error"] for s in skipped}))
            raise HTTPException(404, detail)
        scored = [ScoredCandidate(c, score(c.geometry, model, index)) for c in kept]
        t2 = time.perf_counter()
        top = rank(scored, n=n)
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
                "weight_set": model.weight_set, "routes": routes,
                "candidates_total": len(kept) + len(dropped),
                "candidates_deduped": len(kept), "skipped": skipped,
                "timings_ms": {"brouter": round((t1 - t0) * 1000),
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
