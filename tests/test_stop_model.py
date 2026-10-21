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


def test_with_overrides(model):
    m2 = model.with_overrides({"signal": 0.0, "stop": 1.0})
    assert m2.p("signal") == 0.0 and m2.p("stop") == 1.0
    assert m2.weight_set == model.weight_set + "+custom"
    assert model.p("signal") == 0.4  # original untouched
    assert m2.p("give_way") == model.p("give_way")


def test_with_overrides_errors(model):
    with pytest.raises(ValueError):
        model.with_overrides({"signal": 1.5})
    with pytest.raises(ValueError):
        model.with_overrides({"signal": -0.1})
    with pytest.raises(KeyError, match="signal"):
        model.with_overrides({"bogus": 0.1})


def test_blend(model, combined):
    b = stop_model.blend(model, combined, 0.25)
    for c in CAUSES:
        assert b.p(c) == pytest.approx(0.75 * model.p(c) + 0.25 * combined.p(c))
        assert b.mean_stop_s(c) == pytest.approx(
            0.75 * model.mean_stop_s(c) + 0.25 * combined.mean_stop_s(c))
    assert b.weight_set == "blend(prior,combined,0.25)"
    assert stop_model.blend(model, combined, 0).p("signal") == model.p("signal")
    assert stop_model.blend(model, combined, 1).p("signal") == combined.p("signal")
    with pytest.raises(ValueError):
        stop_model.blend(model, combined, 1.1)


def test_brouter_costs_prior(model):
    c = model.brouter_costs()
    assert set(c) == {"cost_signal", "cost_xing_signal", "cost_give_way", "cost_stop",
                      "cost_mini_rb", "cost_rb_entry"}
    assert c["cost_signal"] == 300
    assert c["cost_mini_rb"] == c["cost_rb_entry"]
    assert all(isinstance(v, int) and 0 <= v <= 1000 for v in c.values())


def test_brouter_costs_p_stop_zero(model):
    assert model.with_overrides({"stop": 0}).brouter_costs()["cost_stop"] == 0


def test_brouter_costs_signal_is_anchor(model):
    assert model.with_overrides({"signal": 0.5}).brouter_costs()["cost_signal"] == 300
    assert model.brouter_costs(anchor=200)["cost_signal"] == 200


def test_brouter_costs_p_signal_zero_still_anchored(model):
    c = model.with_overrides({"signal": 0}).brouter_costs()
    assert c["cost_signal"] == 300 and all(0 <= v <= 1000 for v in c.values())
