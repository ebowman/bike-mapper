"""Thin client for a local BRouter RouteServer (scripts/run_brouter.sh serve)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import requests

DEFAULT_URL = "http://localhost:17777"
HEALTH_PAIR = [(-6.2825, 53.2990), (-6.2150, 53.2210)]
MAX_FLOW_SCALE = 10.0
MAX_COST = 1000.0
MIN_LANE_BONUS, MAX_LANE_BONUS = 0.5, 1.0
# emq.27 straightness params: name -> (min, max)
RANGED_PARAMS = {"turn_cost": (0.0, 2000.0), "lane_exit_cost": (0.0, 1000.0), "cycleway_base": (0.5, 2.0)}

# Same value sets and precedence as scripts/build_cycle_overlay.py classify() (duplicated: that module imports
# osmium at top level, which the server does not need). Keep in sync.
CYCLEWAY_KEYS = ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both")
LANE_VALUES = {"lane", "shared_lane", "share_busway", "opposite_lane"}
TRACK_VALUES = {"track", "opposite_track", "separate"}


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
    # per-BRouter-message-row dicts (see parse_messages); [] when the response had no messages
    segments: list = field(default_factory=list)
    # parallel to geometry: metres, or None when the coordinate had no third element
    elevations: list = field(default_factory=list)
    # set by flowplan.plan: mode, heading_deg, via_points, radius_m/turnaround, iterations, length_km
    plan: dict | None = None

    @property
    def key(self) -> str:
        return f"{self.variant}/alt{self.alt}"

    @property
    def route_id(self) -> str:
        """Unique id within a plan response: planned loops / out-and-backs include the heading
        and via-point set index (`flow_hi@45.2/alt0`); one-way and /api/route candidates use the bare key."""
        h = (self.plan or {}).get("heading_deg")
        if h is None:
            return self.key
        s = (self.plan or {}).get("set", 0)
        return f"{self.variant}@{h:g}.{s}/alt{self.alt}"


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
        elif k == "lane_bonus":
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"lane_bonus must be numeric, got {v!r}") from None
            if not math.isfinite(f) or not MIN_LANE_BONUS <= f <= MAX_LANE_BONUS:
                raise ValueError(f"lane_bonus must be finite and within "
                                 f"{MIN_LANE_BONUS}..{MAX_LANE_BONUS}, got {v!r}")
        elif k in RANGED_PARAMS:
            lo, hi = RANGED_PARAMS[k]
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be numeric, got {v!r}") from None
            if not math.isfinite(f) or not lo <= f <= hi:
                raise ValueError(f"{k} must be finite and within {lo:g}..{hi:g}, got {v!r}")
        elif str(k).startswith("cost_"):
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be numeric, got {v!r}") from None
            if not math.isfinite(f) or not 0 <= f <= MAX_COST:
                raise ValueError(f"{k} must be finite and within 0..{MAX_COST:g}, got {v!r}")
        out[str(k)] = v
    return out


def _num(row, idx, scale=1.0):
    try:
        return float(row[idx]) / scale
    except (TypeError, ValueError, IndexError):
        return 0.0


def parse_messages(messages) -> list:
    """BRouter geojson `messages` (row 0 = header, then one row per routed node; all cells strings)
    -> [{lon, lat, dist_m, way_tags, node_cost, initial_cost, turn_cost, cost_per_km, time_s}].
    Columns are looked up by header name, so missing/reordered columns are tolerated. Lon/lat are
    microdegrees in the raw rows. Each row describes the segment ENDING at its node, with the way
    tags of that segment. Time is cumulative in BRouter; time_s here is the per-segment delta."""
    if not messages or not isinstance(messages, list) or len(messages) < 2:
        return []
    col = {str(n): i for i, n in enumerate(messages[0])}

    def get(row, name, scale=1.0):
        i = col.get(name)
        return 0.0 if i is None else _num(row, i, scale)

    out, prev_t = [], 0.0
    for row in messages[1:]:
        if not isinstance(row, list):
            continue
        tags = {}
        i = col.get("WayTags")
        if i is not None and i < len(row) and isinstance(row[i], str):
            for tok in row[i].split():
                k, _, v = tok.partition("=")
                if k:
                    tags[k] = v
        t = get(row, "Time")
        out.append({"lon": get(row, "Longitude", 1e6), "lat": get(row, "Latitude", 1e6),
                    "dist_m": get(row, "Distance"), "way_tags": tags,
                    "node_cost": get(row, "NodeCost"), "initial_cost": get(row, "InitialCost"),
                    "turn_cost": get(row, "TurnCost"), "cost_per_km": get(row, "CostPerKm"),
                    "time_s": max(0.0, t - prev_t)})
        prev_t = t
    return out


def classify_tags(tags: dict) -> str | None:
    """'path' (highway=cycleway), 'track', 'lane' or None. Path wins; track beats lane."""
    if tags.get("highway") == "cycleway":
        return "path"
    kinds = set()
    for key in CYCLEWAY_KEYS:
        v = tags.get(key)
        if v in TRACK_VALUES:
            kinds.add("track")
        elif v in LANE_VALUES:
            kinds.add("lane")
    return "track" if "track" in kinds else "lane" if kinds else None


def cycle_km(segments) -> dict:
    """Kilometres of a route on cycle infrastructure: {path, lane, track, total_km}."""
    km = {"path": 0.0, "lane": 0.0, "track": 0.0}
    total = 0.0
    for sg in segments or []:
        d = float(sg.get("dist_m", 0) or 0)
        total += d
        kind = classify_tags(sg.get("way_tags") or {})
        if kind:
            km[kind] += d
    return {**{k: v / 1000 for k, v in km.items()}, "total_km": total / 1000}


def parse_geojson(data: dict, variant: str = "", profile: str = "", alt: int = 0,
                  params: dict | None = None) -> Candidate:
    feat = data["features"][0]
    props = feat["properties"]
    coords = feat["geometry"]["coordinates"]
    geom = [(float(c[0]), float(c[1])) for c in coords]
    elevs = [float(c[2]) if len(c) > 2 and c[2] is not None else None for c in coords]
    return Candidate(variant=variant or profile, profile=profile, alt=alt, geometry=geom,
                     length_m=float(props["track-length"]),
                     ascent_m=float(props.get("filtered ascend", 0) or 0),
                     time_s=float(props.get("total-time", 0) or 0),
                     cost=float(props.get("cost", 0) or 0), params=dict(params or {}),
                     segments=parse_messages(props.get("messages")), elevations=elevs)


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
