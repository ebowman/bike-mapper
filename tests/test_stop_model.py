import pytest
from flowplan import stop_model

CAUSES = ["signal", "stop", "give_way", "rb_entry", "xing_signal",
          "yield_infer", "yield_equal"]


@pytest.fixture(scope="module")
def model():
    return stop_model.load()


def test_all_causes_present(model):
    for c in CAUSES:
        assert c in model.causes


def test_probability_bounds(model):
    for c in CAUSES:
        p = model.p(c)
        assert 0 <= p <= 1
        assert model.causes[c]["p_lo"] <= p <= model.causes[c]["p_hi"]
        assert model.mean_stop_s(c) > 0


def test_precedence(model):
    assert list(model.classes) == CAUSES


def test_expected_stops(model):
    assert stop_model.expected_stops(["signal", "give_way"], model) == pytest.approx(0.158 + 0.041)
    assert stop_model.expected_stops([], model) == 0


def test_midway_background(model):
    assert model.midway_background_p == 0.003
