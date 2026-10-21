"""Rank scored candidates: lowest expected_stops + turn_weight * turns first, with a distance guard."""
from __future__ import annotations

from dataclasses import dataclass, field

from .brouter import Candidate
from .scoring import RouteScore


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


def rank(scored: list[ScoredCandidate], n: int = 4, guard: float = 1.3,
         min_keep: int = 3, turn_weight: float = DEFAULT_TURN_WEIGHT) -> list[ScoredCandidate]:
    """Sort by expected_stops + turn_weight * turns asc (tie: longer longest_straight_km, then shorter). Drop candidates longer than
    guard x the shortest (guard <= 0 disables the guard) unless that would leave fewer than min_keep. Return the top n
    with rank (1-based) and delta_vs_fastest ({stops, km, turns} vs fastbike/alt0, or None)."""
    if not scored:
        return []
    ordered = sorted(scored, key=lambda s: (s.expected_stops + turn_weight * s.score.turns,
                                            -s.score.longest_straight_km, s.length_m))
    limit = guard * min(s.length_m for s in scored) if guard > 0 else float('inf')  # 0 = off
    within = [s for s in ordered if s.length_m <= limit]
    pool = within if len(within) >= min_keep else ordered
    top = pool[:max(n, 0)]
    ref = next((s for s in scored if s.cand.variant == "fastbike" and s.cand.alt == 0), None)
    for i, s in enumerate(top, 1):
        s.rank = i
        s.delta_vs_fastest = None if ref is None else {
            "stops": s.expected_stops - ref.expected_stops,
            "km": (s.length_m - ref.length_m) / 1000,
            "turns": s.score.turns - ref.score.turns,
        }
    return top
