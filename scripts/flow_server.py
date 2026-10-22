"""Flow route planner API. Run: uv run scripts/flow_server.py [--region ireland] [--port 8081]
[--brouter http://localhost:17777]"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from flowplan.brouter import DEFAULT_URL
from flowplan.pick import PickStore
from flowplan.pick import register as register_pick
from flowplan.service import (  # noqa: F401 - re-exported for tests/tools
    BBOX,
    DEFAULT_SCALES,
    STRAIGHT_DEFAULTS,
    PlannerService,
    ServiceError,
    parse_latlon,
    variants_for,
)

log = logging.getLogger("flow_server")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(region: str = "ireland", brouter_url: str = DEFAULT_URL, client=None,
               index=None, model=None, model_path=None, dem=None) -> FastAPI:
    app = FastAPI(title="flow planner")
    svc = PlannerService.create(region, brouter_url, client, index, model, model_path, dem)
    try:
        if not svc.client.health():
            log.warning("BRouter not healthy at %s; start it with `scripts/run_brouter.sh serve`",
                        brouter_url)
    except Exception as e:  # noqa: BLE001 - never exit on startup
        log.warning("BRouter health check failed: %s", e)

    def call(fn, *a, **k):
        try:
            return fn(*a, **k)
        except ServiceError as e:
            raise HTTPException(e.status, e.detail) from None

    @app.get("/api/health")
    def health():
        return svc.health()

    @app.get("/api/model")
    def model_info():
        return svc.model_info()

    @app.get("/api/route")
    def route(request: Request, from_: str = Query(alias="from"), to: str = Query(), n: int = 4):
        return call(svc.route, from_, to, n, request.query_params)

    @app.get("/api/plan")
    def plan(request: Request):
        return call(svc.plan, request.query_params)

    register_pick(app, PickStore())

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
