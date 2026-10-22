"""Rank scored candidates: lowest expected_stops + turn_weight * turns first, with a distance guard."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .brouter import Candidate
from .climbs import climb_score, detect_climbs, elevation_stats
from .scoring import RouteScore, score
from .turns import turn_metrics

OBJECTIVES = ("flow", "climb", "flat")


@dataclass
class ScoredCandidate:
    cand: Candidate
    score: RouteScore
    rank: int = 0
    delta_vs_fastest: dict | None = None
    extra: dict = field(default_factory=dict)

    @property
    def length_m(self) -> float:
        return self.cand.length_m

    @property
    def expected_stops(self) -> float:
        return self.score.expected_stops


DEFAULT_TURN_WEIGHT = 0.33


def score_candidate(c: Candidate, model, index, region: str = "ireland") -> ScoredCandidate:
    """Flow score + turn metrics + elevation/climb stats for one candidate (shared by /api/route and /api/plan).
    extra: ascent_m, descent_m (None without elevations), climbs [dict], climb_score, hardest_climb (dict|None)."""
    sc = score(c.geometry, model, index)
    for k, v in turn_metrics(c.geometry, c.segments, sc.hits, region=region).items():
        setattr(sc, k, v)
    st = elevation_stats(c.geometry, c.elevations)
    have = st["max_ele"] is not None
    climbs = detect_climbs(c.geometry, c.elevations) if have else []
    cs = climb_score(climbs)
    return ScoredCandidate(c, sc, extra={
        "ascent_m": st["ascent_m"] if have else c.ascent_m,
        "descent_m": st["descent_m"] if have else None,
        "climbs": [asdict(x) for x in climbs], "climb_score": cs["score"],
        "hardest_climb": asdict(cs["hardest"]) if cs["hardest"] else None})


def rank(scored: list[ScoredCandidate], n: int = 4, guard: float = 1.3,
         min_keep: int = 3, turn_weight: float = DEFAULT_TURN_WEIGHT, objective: str = "flow",
         length_range: tuple | None = None) -> list[ScoredCandidate]:
    """objective flow: expected_stops + turn_weight * turns asc (tie: longer longest_straight_km, then shorter).
    climb: climb_score desc, ties by the flow score. flat: ascent_m asc, ties by the flow score.
    length_range (min_km, max_km) replaces the distance guard (loops, out-and-backs): candidates outside it
    are dropped. Otherwise drop candidates longer than guard x the shortest (guard <= 0 disables) unless that
    would leave fewer than min_keep. Return the top n with rank (1-based) and delta_vs_fastest
    ({stops, km, turns} vs the fastbike/alt0 candidate of the same heading, or None)."""
    if objective not in OBJECTIVES:
        raise ValueError(f"objective must be one of {', '.join(OBJECTIVES)}, got {objective!r}")
    if not scored:
        return []

    def flow(s):
        return (s.expected_stops + turn_weight * s.score.turns, -s.score.longest_straight_km, s.length_m)

    def key(s):
        if objective == "climb":
            return (-s.extra.get("climb_score", 0.0), *flow(s))
        if objective == "flat":
            return (s.extra.get("ascent_m", s.cand.ascent_m), *flow(s))
        return flow(s)

    ordered = sorted(scored, key=key)
    if length_range is not None:
        lo, hi = length_range
        pool = [s for s in ordered if lo - 1e-6 <= s.length_m / 1000 <= hi + 1e-6]
    else:
        limit = guard * min(s.length_m for s in scored) if guard > 0 else float('inf')  # 0 = off
        within = [s for s in ordered if s.length_m <= limit]
        pool = within if len(within) >= min_keep else ordered
    top = pool[:max(n, 0)]

    def heading(s):
        return (s.cand.plan or {}).get("heading_deg")

    for i, s in enumerate(top, 1):
        h = heading(s)
        ref = next((r for r in scored if r.cand.variant == "fastbike" and r.cand.alt == 0
                    and (h is None or heading(r) == h)), None)
        s.rank = i
        s.delta_vs_fastest = None if ref is None else {
            "stops": s.expected_stops - ref.expected_stops,
            "km": (s.length_m - ref.length_m) / 1000,
            "turns": s.score.turns - ref.score.turns,
        }
    return top
