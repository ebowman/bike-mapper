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

import json
import os
from dataclasses import dataclass
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
