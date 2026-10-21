"""Validated per-class stop-probability model.

Source: docs/research/stop-model-validation.md (combined headline, leader r=25 m,
units with >= 5 passes); table in data/model/stop_model.json.

Decision rules:
* The probability p applies PER ARRIVAL EVENT at a node. The dhy.10 `amount`
  column is ignored (the 0.5 on yield_equal was a prior, superseded by the
  measured p).
* When several events fire at the same arrival (same node_id, way_id, dir),
  keep only the highest-precedence class (see CLASSES) and drop the rest.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Precedence order, highest first.
CLASSES = ("signal", "stop", "give_way", "rb_entry", "xing_signal",
           "yield_infer", "yield_equal")

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "model" / "stop_model.json"


@dataclass(frozen=True)
class StopModel:
    causes: dict
    midway_background_p: float = 0.0
    rules: str = ""

    @property
    def classes(self) -> tuple:
        return CLASSES

    def p(self, cause: str) -> float:
        return float(self.causes[cause]["p"])

    def mean_stop_s(self, cause: str) -> float:
        return float(self.causes[cause]["mean_stop_s"])


def load(path=None) -> StopModel:
    with open(path or DEFAULT_PATH) as f:
        d = json.load(f)
    return StopModel(causes=d["causes"],
                     midway_background_p=d.get("midway_background_p", 0.0),
                     rules=d.get("rules", ""))


def expected_stops(causes, model: StopModel | None = None) -> float:
    """Sum of p over a list of causes (caller must already have deduped)."""
    m = model or load()
    return sum(m.p(c) for c in causes)
