import json

import pytest
from flowplan import stop_model

CAUSES = ["signal", "stop", "give_way", "rb_entry", "xing_signal",
          "yield_infer", "yield_equal"]
SETS = ["combined", "ireland", "prior"]


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("FLOW_WEIGHTS", raising=False)


@pytest.fixture
def model():
    return stop_model.load()


@pytest.fixture
def combined():
    return stop_model.load(weights="combined")


def test_default_is_prior(model):
    assert model.weight_set == "prior"
    assert model.p("signal") == 0.40


@pytest.mark.parametrize("ws", SETS)
def test_sets_have_seven_causes(ws):
    m = stop_model.load(weights=ws)
    assert m.weight_set == ws
    assert sorted(m.causes) == sorted(CAUSES)
    for c in CAUSES:
        assert 0 <= m.causes[c]["p_lo"] <= m.p(c) <= m.causes[c]["p_hi"] <= 1
        assert m.mean_stop_s(c) > 0
        assert m.causes[c]["source"]


def test_ireland_differs_from_combined(combined):
    ire = stop_model.load(weights="ireland")
    assert ire.p("give_way") == 0.0428
    assert ire.p("give_way") != combined.p("give_way")
    assert ire.p("xing_signal") == ire.p("signal")


def test_precedence_from_json(model):
    with open(stop_model.DEFAULT_PATH) as f:
        prec = json.load(f)["precedence"]
    assert prec == CAUSES
    assert list(model.classes) == prec


def test_unknown_cause(model):
    with pytest.raises(KeyError, match="known causes.*signal.*yield_equal"):
        model.p("nope")
    with pytest.raises(KeyError, match="known causes"):
        model.mean_stop_s("nope")


def test_unknown_weights():
    with pytest.raises(ValueError, match="combined, ireland, prior"):
        stop_model.load(weights="bogus")


def test_env_override(monkeypatch):
    monkeypatch.setenv("FLOW_WEIGHTS", "ireland")
    assert stop_model.load().weight_set == "ireland"
    assert stop_model.load(weights="combined").weight_set == "combined"
    monkeypatch.setenv("FLOW_WEIGHTS", "bogus")
    with pytest.raises(ValueError):
        stop_model.load()


def test_expected_stops(combined):
    assert stop_model.expected_stops(["signal", "give_way"], combined) == pytest.approx(0.158 + 0.041)
    assert stop_model.expected_stops([], combined) == 0
    assert stop_model.expected_stops(["signal"]) == pytest.approx(0.40)


def test_midway_background(model):
    assert model.midway_background_p == 0.003
