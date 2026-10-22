"""Pick-on-map bridge: a short-lived in-memory store of points the user clicked in the web planner
for the MCP assistant (POST/GET /api/pick/{token}). See docs/mcp.md."""
from __future__ import annotations

import re
import threading
import time

from fastapi import FastAPI, HTTPException

TTL_S = 600
MAX_POINTS = 2
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class PickStore:
    def __init__(self, ttl_s: float = TTL_S, clock=time.time):
        self.ttl_s, self.clock = ttl_s, clock
        self._d: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _purge(self) -> None:
        now = self.clock()
        for k in [k for k, v in self._d.items() if now - v["created_at"] > self.ttl_s]:
            del self._d[k]

    def put(self, token: str, points: list[dict]) -> dict:
        with self._lock:
            self._purge()
            self._d[token] = {"points": points, "created_at": self.clock()}
            return self._d[token]

    def get(self, token: str) -> dict | None:
        with self._lock:
            self._purge()
            return self._d.get(token)


def _clean(body) -> list[dict]:
    pts = body.get("points") if isinstance(body, dict) else None
    if not isinstance(pts, list) or not 1 <= len(pts) <= MAX_POINTS:
        raise HTTPException(400, f"'points' must be a list of 1 to {MAX_POINTS} points")
    out = []
    for p in pts:
        try:
            lat, lon = float(p["lat"]), float(p["lon"])
        except (TypeError, KeyError, ValueError):
            raise HTTPException(400, "each point needs numeric lat and lon") from None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise HTTPException(400, "lat/lon out of range")
        q = {"lat": lat, "lon": lon}
        if p.get("label") is not None:
            q["label"] = str(p["label"])[:200]
        out.append(q)
    return out


def register(app: FastAPI, store: PickStore) -> None:
    def check(token: str) -> None:
        if not TOKEN_RE.match(token):
            raise HTTPException(400, "token must match [A-Za-z0-9_-]{8,64}")

    @app.post("/api/pick/{token}")
    def put_pick(token: str, body: dict):
        check(token)
        return store.put(token, _clean(body))

    @app.get("/api/pick/{token}")
    def get_pick(token: str):
        check(token)
        v = store.get(token)
        if v is None:
            raise HTTPException(404, "no points for this token (not sent yet, or expired)")
        return v
