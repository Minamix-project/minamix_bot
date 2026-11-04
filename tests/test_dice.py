from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from src.utils import dice
from src.utils.dice import MAX_TOTAL_DRAWS, ParseError, RollLimitError, roll

def test_basic_roll():
    result = roll("1d6")
    assert "d6" in result[0]

def test_rejects_too_many_dice():
    result, _private = roll("201d6")
    assert "Maximum 200 dés" in result


@pytest.mark.parametrize("expression", ["201df", "201wh45", "gb 201", "wng 201", "sr201", "201cod", "201wod8"])
def test_all_dice_systems_enforce_group_limit_before_drawing(monkeypatch, expression):
    draw = Mock(side_effect=AssertionError("No random draws should occur"))
    monkeypatch.setattr(dice, "_d", draw)
    result, _private = roll(expression)
    assert "Maximum 200 dés" in result
    draw.assert_not_called()


@pytest.mark.parametrize("expression", ["0d20", "0df", "0wh45", "gb 0", "wng 0"])
def test_zero_dice_is_an_explicit_error(expression):
    result, _private = roll(expression)
    assert "au moins 1 dé" in result


def test_twenty_sets_of_two_hundred_dice_remain_supported(monkeypatch):
    draw = Mock(return_value=20)
    monkeypatch.setattr(dice, "_d", draw)
    result, _private = roll("20 200d20")
    assert draw.call_count == 4000
    assert result.count("**4000**") == 20
    assert len(result) > 4096


def test_global_budget_covers_multiple_expressions_and_sets(monkeypatch):
    draw = Mock(return_value=20)
    monkeypatch.setattr(dice, "_d", draw)
    with pytest.raises(RollLimitError, match="tirages par commande"):
        roll("20 200d20;20 200d20;20 200d20")
    assert draw.call_count == MAX_TOTAL_DRAWS


@pytest.mark.parametrize("expression", ["200d1 ie1", "200d1 ir1"])
def test_global_budget_covers_explosions_and_rerolls(monkeypatch, expression):
    draw = Mock(return_value=1)
    monkeypatch.setattr(dice, "_d", draw)
    with pytest.raises(RollLimitError):
        roll(expression)
    assert draw.call_count == MAX_TOTAL_DRAWS
    # Exhausting one command must not consume the next command's allowance.
    assert "❌" not in roll("1d6")[0]


def test_budget_is_shared_by_fate_and_standard_dice(monkeypatch):
    monkeypatch.setattr(dice, "MAX_TOTAL_DRAWS", 201)
    monkeypatch.setattr(dice, "_d", lambda _sides: 2)
    with pytest.raises(RollLimitError):
        roll("200df;2d6")


def test_concurrent_rolls_have_independent_budgets(monkeypatch):
    monkeypatch.setattr(dice, "_d", lambda _sides: 20)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(roll, ["20 200d20", "20 200d20"]))
    assert all(result.count("**4000**") == 20 for result, _private in results)


@pytest.mark.parametrize("expression", ["", " ", "; ;", "1d6;1d6;1d6;1d6;1d6", "1d6 ! " + "x" * 1000, "1d" + "9" * 100])
def test_input_bounds_are_checked_before_randomness(monkeypatch, expression):
    draw = Mock()
    monkeypatch.setattr(dice, "_d", draw)
    with pytest.raises(ParseError):
        roll(expression)
    draw.assert_not_called()


def test_repeat_and_side_limits_are_explicit(monkeypatch):
    draw = Mock()
    monkeypatch.setattr(dice, "_d", draw)
    assert "entre 1 et 20" in roll("21 1d6")[0]
    assert "faces par dé" in roll("1d1000001")[0]
    draw.assert_not_called()


def test_private_flag_and_comments_survive(monkeypatch):
    monkeypatch.setattr(dice, "_d", lambda _sides: 4)
    output, private = roll("p 2d6 ! Mon attaque")
    assert private
    assert output.startswith("**Mon attaque**")
    assert "**8**" in output
