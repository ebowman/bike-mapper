"""Validated per-class stop-probability model.

Source: docs/research/stop-model-validation.md (combined headline, leader r=25 m,
units with >= 5 passes); table in data/model/stop_model.json.

Decision rules:
* The probability p applies PER ARRIVAL EVENT at a node. The dhy.10 `amount`
  column is ignored (the 0.5 on yield_equal was a prior, superseded by the
  measured p).
* Weight sets: data/model/stop_model.json holds three named sets (combined,
  ireland, prior) under `weight_sets`; `default_weight_set` ("prior") is used
  unless `load(weights=...)` is given. If weights is None the environment
  variable FLOW_WEIGHTS (combined|ireland|prior) overrides the default.
* When several events fire at the same arrival (same node_id, way_id, dir),
  keep only the highest-precedence class (the JSON `precedence` list) and drop the rest.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "model" / "stop_model.json"


@dataclass(frozen=True)
class StopModel:
    causes: dict
    midway_background_p: float = 0.0
    rules: str = ""
    weight_set: str = ""
    precedence: tuple = ()

    @property
    def classes(self) -> tuple:
        """Precedence order, highest first (from the JSON `precedence` list)."""
        return self.precedence

    def _cause(self, cause: str) -> dict:
        try:
            return self.causes[cause]
        except KeyError:
            raise KeyError(f"unknown cause {cause!r}; known causes: "
                           f"{', '.join(self.causes)}") from None

    def p(self, cause: str) -> float:
        return float(self._cause(cause)["p"])

    def mean_stop_s(self, cause: str) -> float:
        return float(self._cause(cause)["mean_stop_s"])

    def brouter_costs(self, anchor: float = 300) -> dict[str, int]:
        """BRouter flow.brf node costs (profile:cost_<x>=<n>) derived from this p-table.

        cost(class) = anchor x (p x mean_stop_s)/(p_signal x mean_stop_s_signal), the same formula as
        the 'weight' column of docs/research/stop-model-validation.md (weight = 300 x (p x mean stop
        seconds) / (same for signals); this version omits the mid-way background subtraction).
        Signals are the anchor, so cost_signal == anchor (also if p_signal is overridden to 0:
        then the reference is the largest class p x mean_stop_s). Clamped to [0, 1000], rounded to int.
        rb_entry feeds both cost_mini_rb and cost_rb_entry."""
        ref = self.p("signal") * self.mean_stop_s("signal")
        if ref <= 0:
            # p_signal overridden to 0: no signal reference; fall back to the largest class
            # (p x mean_stop_s), so the costs stay finite and relative to each other.
            ref = max(float(c["p"]) * float(c["mean_stop_s"]) for c in self.causes.values())
        if ref <= 0:
            return {"cost_signal": round(min(1000.0, max(0.0, anchor))), "cost_xing_signal": 0,
                    "cost_give_way": 0, "cost_stop": 0, "cost_mini_rb": 0, "cost_rb_entry": 0}

        def cost(cause: str) -> int:
            return round(min(1000.0, max(0.0, anchor * self.p(cause) * self.mean_stop_s(cause) / ref)))

        rb = cost("rb_entry")
        return {"cost_signal": round(min(1000.0, max(0.0, anchor))), "cost_xing_signal": cost("xing_signal"),
                "cost_give_way": cost("give_way"), "cost_stop": cost("stop"),
                "cost_mini_rb": rb, "cost_rb_entry": rb}

    def with_overrides(self, p: dict) -> StopModel:
        """Copy with per-cause p replaced. 0 <= p <= 1 (ValueError); unknown cause KeyError.
        weight_set gains a '+custom' suffix (unchanged if p is empty)."""
        causes = copy.deepcopy(self.causes)
        for cause, v in p.items():
            if cause not in causes:
                raise KeyError(f"unknown cause {cause!r}; known causes: {', '.join(causes)}")
            f = float(v)
            if not 0.0 <= f <= 1.0:  # also rejects NaN
                raise ValueError(f"p for {cause!r} must be within 0..1, got {v!r}")
            causes[cause]["p"] = f
        return replace(self, causes=causes,
                       weight_set=self.weight_set + "+custom" if p else self.weight_set)


def blend(a: StopModel, b: StopModel, alpha: float) -> StopModel:
    """Per-class linear blend (1-alpha)*a + alpha*b of p and mean_stop_s; alpha in [0, 1]."""
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"blend alpha must be within 0..1, got {alpha!r}")
    causes = copy.deepcopy(a.causes)
    for cause in causes:
        ca, cb = a._cause(cause), b._cause(cause)
        for k in ("p", "mean_stop_s"):
            causes[cause][k] = (1 - alpha) * float(ca[k]) + alpha * float(cb[k])
    return replace(a, causes=causes, weight_set=f"blend({a.weight_set},{b.weight_set},{alpha:.2f})")


def load(path=None, weights=None) -> StopModel:
    with open(path or DEFAULT_PATH) as f:
        d = json.load(f)
    sets = d["weight_sets"]
    if weights is None:
        weights = os.environ.get("FLOW_WEIGHTS") or d["default_weight_set"]
    if weights not in sets:
        raise ValueError(f"unknown weights {weights!r}; valid names: "
                         f"{', '.join(sets)}")
    return StopModel(causes=sets[weights],
                     midway_background_p=d.get("midway_background_p", 0.0),
                     rules=d.get("rules", ""),
                     weight_set=weights,
                     precedence=tuple(d["precedence"]))


def expected_stops(causes, model: StopModel | None = None) -> float:
    """Sum of p over a list of causes (caller must already have deduped)."""
    m = model or load()
    return sum(m.p(c) for c in causes)
