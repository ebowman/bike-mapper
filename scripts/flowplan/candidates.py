"""Generate candidate routes (variants x alternatives) and drop near-duplicates."""
from __future__ import annotations

import functools
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import shapely
from pyproj import Transformer

from .brouter import BRouterClient, Candidate, validate_params
from .scoring import REGION_CRS

__all__ = ["DEFAULT_VARIANTS", "DEFAULT_WORKERS", "Candidate", "Variant", "dedupe", "generate",
           "lanes_variant"]

# Client concurrency; keep <= BRouter server threads (THREADS in scripts/run_brouter.sh).
DEFAULT_WORKERS = 4


@dataclass(frozen=True)
class Variant:
    name: str
    profile: str
    params: dict = field(default_factory=dict, hash=False)


# 41w.15: the "Fastest" baseline is the flow profile with node costs off (flow_scale 0), so it obeys the same
# rideability rules as every other candidate. Every key the server sends per request is fixed here explicitly
# (a variant's own params win over profile_params), so request lane_bonus/turn_cost/costs never leak into it.
# cycleway_base stays at the profile default 1.0 (parity rules); turn_cost 90 = stock fastbike's turncost.
BASELINE_PARAMS = {"flow_scale": 0, "lane_bonus": 1.0, "lane_exit_cost": 0, "turn_cost": 90, "cycleway_base": 1.0,
                   "cost_signal": 300, "cost_xing_signal": 300, "cost_give_way": 80, "cost_stop": 60,
                   "cost_mini_rb": 80, "cost_rb_entry": 150}

DEFAULT_VARIANTS = (
    Variant("fastbike", "flow", dict(BASELINE_PARAMS)),
    Variant("flow_lo", "flow", {"flow_scale": 0.5}),
    Variant("flow", "flow", {"flow_scale": 1.0}),
    Variant("flow_hi", "flow", {"flow_scale": 2.0}),
)

# Optional fifth variant (flow_server lanes_variant=1): flow at default stop weights with a cycle-infrastructure bonus.
LANES_STEP = 0.2
LANES_FLOOR = 0.5


def lanes_variant(lane_bonus: float = 1.0) -> Variant:
    """flow_lanes: lane_bonus max(0.5, lane_bonus - 0.2), always at least as strong as the current setting."""
    return Variant("flow_lanes", "flow", {"flow_scale": 1.0,
                                          "lane_bonus": round(max(LANES_FLOOR, float(lane_bonus) - LANES_STEP), 4)})


@functools.lru_cache(maxsize=8)
def _transformer(region: str) -> Transformer:
    return Transformer.from_crs("EPSG:4326", REGION_CRS[region], always_xy=True)


def project_line(geometry, region: str = "ireland"):
    """lon/lat polyline -> shapely LineString in the region's metric CRS (empty LineString if < 2 points)."""
    tf = _transformer(region)
    xs, ys = tf.transform([p[0] for p in geometry], [p[1] for p in geometry])
    return shapely.linestrings(list(zip(xs, ys))) if len(xs) > 1 else shapely.LineString()


def overlap_fraction(line, buf) -> float:
    """Fraction of line's length inside the (buffer) polygon buf; 0 for empty or zero-length lines."""
    if line.is_empty or line.length <= 0 or buf.is_empty:
        return 0.0
    return shapely.intersection(line, buf).length / line.length


def dedupe(cands: list[Candidate], region: str = "ireland", buffer_m: float = 20.0,
           overlap: float = 0.9) -> tuple[list[Candidate], list[Candidate]]:
    """Input order = priority. Drop a candidate if >= overlap of its length lies within
    buffer_m of a kept one; set duplicate_of on dropped ones."""
    kept, dropped, buffers = [], [], []
    for c in cands:
        line = project_line(c.geometry, region)
        dup = None
        for k, buf in zip(kept, buffers):
            if overlap_fraction(line, buf) >= overlap:
                dup = k
                break
        if dup is not None:
            c.duplicate_of = dup.key
            dropped.append(c)
        else:
            kept.append(c)
            buffers.append(shapely.buffer(line, buffer_m) if not line.is_empty else shapely.Polygon())
    return kept, dropped


def generate(client: BRouterClient, start, end, variants=DEFAULT_VARIANTS, alts=(0, 1, 2, 3),
             max_workers: int = DEFAULT_WORKERS, region: str = "ireland",
             profile_params: dict | None = None):
    """Return (kept, dropped, skipped). skipped = [{variant, alt, error}] for failed
    requests; BRouterUnavailable propagates. profile_params (e.g. cost_* from
    StopModel.brouter_costs) are merged into every variant's params (a variant's own params win, so the baseline keeps its fixed ones). start == end yields no candidates."""
    start, end = (float(start[0]), float(start[1])), (float(end[0]), float(end[1]))
    if start == end:
        return [], [], []
    if profile_params:
        variants = tuple(Variant(v.name, v.profile, {**profile_params, **v.params}) for v in variants)
    for v in variants:
        validate_params(v.params)
    jobs = [(v, a) for v in variants for a in alts]

    def run(job):
        v, a = job
        c, err = client.route([start, end], v.profile, a, v.params)
        if c is not None:
            c.variant = v.name
        return v, a, c, err

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(run, jobs))  # preserves job order
    skipped = [{"variant": v.name, "alt": a, "error": err or "no route"}
               for v, a, c, err in results if c is None]
    kept, dropped = dedupe([r[2] for r in results if r[2] is not None], region)
    return kept, dropped, skipped
