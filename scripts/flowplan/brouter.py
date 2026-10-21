"""Thin client for a local BRouter RouteServer (scripts/run_brouter.sh serve)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import requests

DEFAULT_URL = "http://localhost:17777"
HEALTH_PAIR = [(-6.2825, 53.2990), (-6.2150, 53.2210)]
MAX_FLOW_SCALE = 10.0
MAX_COST = 1000.0


class BRouterUnavailable(RuntimeError):
    """The BRouter server cannot be reached (not running)."""


@dataclass
class Candidate:
    variant: str
    profile: str
    alt: int
    geometry: list  # [(lon, lat), ...]
    length_m: float
    ascent_m: float
    time_s: float
    cost: float
    params: dict = field(default_factory=dict)
    duplicate_of: str | None = None

    @property
    def key(self) -> str:
        return f"{self.variant}/alt{self.alt}"


def validate_params(params: dict | None) -> dict:
    """Validate per-request profile overrides. The server silently accepts negative or
    empty flow_scale (and 500s on non-numeric), so check it here."""
    out = {}
    for k, v in (params or {}).items():
        if k == "flow_scale":
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"flow_scale must be numeric, got {v!r}") from None
            if not math.isfinite(f) or f <= 0 or f > MAX_FLOW_SCALE:
                raise ValueError(f"flow_scale must be finite, > 0 and <= {MAX_FLOW_SCALE}, got {v!r}")
        elif str(k).startswith("cost_"):
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be numeric, got {v!r}") from None
            if not math.isfinite(f) or not 0 <= f <= MAX_COST:
                raise ValueError(f"{k} must be finite and within 0..{MAX_COST:g}, got {v!r}")
        out[str(k)] = v
    return out


def parse_geojson(data: dict, variant: str = "", profile: str = "", alt: int = 0,
                  params: dict | None = None) -> Candidate:
    feat = data["features"][0]
    props = feat["properties"]
    geom = [(float(c[0]), float(c[1])) for c in feat["geometry"]["coordinates"]]
    return Candidate(variant=variant or profile, profile=profile, alt=alt, geometry=geom,
                     length_m=float(props["track-length"]),
                     ascent_m=float(props.get("filtered ascend", 0) or 0),
                     time_s=float(props.get("total-time", 0) or 0),
                     cost=float(props.get("cost", 0) or 0), params=dict(params or {}))


class BRouterClient:
    def __init__(self, base_url: str = DEFAULT_URL, timeout_s: float = 20):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def route(self, points, profile: str = "fastbike", alternativeidx: int = 0,
              params: dict | None = None) -> tuple[Candidate | None, str | None]:
        """Route through points [(lon, lat), ...]. Returns (candidate, None) on success or
        (None, error_text) on failure; the error is per request (thread-safe)."""
        params = validate_params(params)
        if len(points) < 2:
            return None, "need at least 2 points"
        q = {"lonlats": "|".join(f"{p[0]},{p[1]}" for p in points), "profile": profile,
             "alternativeidx": int(alternativeidx), "format": "geojson"}
        for k, v in params.items():
            q[f"profile:{k}"] = v
        try:
            r = requests.get(f"{self.base_url}/brouter", params=q, timeout=self.timeout_s)
        except requests.ConnectionError as e:
            raise BRouterUnavailable(
                f"BRouter not reachable at {self.base_url}; start it with "
                f"`scripts/run_brouter.sh serve`") from e
        except requests.Timeout:
            return None, f"timeout after {self.timeout_s}s"
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text.strip()[:200]}"
        try:
            data = r.json()
            return parse_geojson(data, profile=profile, alt=int(alternativeidx),
                                 params=params), None
        except (ValueError, KeyError, IndexError, TypeError):
            return None, r.text.strip()[:200] or "empty response"

    def health(self) -> bool:
        try:
            return self.route(HEALTH_PAIR, "fastbike", 0)[0] is not None
        except BRouterUnavailable:
            return False
