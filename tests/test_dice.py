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


@pytest.mark.parametrize("expression,value", [("200d2 ie2", 2), ("20 200d2 r1;20 200d2 r1", 1)])
def test_global_budget_covers_explosions_and_rerolls(monkeypatch, expression, value):
    draw = Mock(return_value=value)
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


@pytest.mark.parametrize("expression,expected", [
    ("1d1+5+2", "8"), ("1d1+2*3", "7"), ("(1d1+2)*3", "9"),
    ("3*1d1+2", "5"), ("1d1-5+2", "-2"), ("-1d1+3", "2"),
    ("1d1+0.5", "1.5"), ("1d1/2", "0.5"), ("1d1/3", "1/3"),
    ("1d1*-0.5", "-0.5"), ("1d1/0.1", "10"), ("1d1+1d1*3", "4"),
    ("(1d1+1d1)*3", "6"), ("3d1-1d1+2", "4"),
])
def test_arithmetic_preserves_all_terms_and_standard_precedence(monkeypatch, expression, expected):
    draw = Mock(return_value=1)
    monkeypatch.setattr(dice, "_d", draw)
    result, _private = roll(expression)
    assert result.endswith(f"→ **{expected}**")


@pytest.mark.parametrize("expression,message", [
    ("1d1 blabla", "non reconnu"), ("1d6 k2 kl1", "incompatibles"),
    ("1d6 r1 ir1", "incompatibles"), ("1d6 e6 ie6", "incompatibles"),
    ("1d6 t5 t6", "répétés"), ("1d6 f1", "nécessitent un seuil"),
    ("1d6 k0", "garder au moins"), ("1d1/0", "Division par zéro"),
    ("1d6/(2-2)", "Division par zéro"), ("1d6+", "non reconnu"),
    ("1d6**2", "non reconnu"), ("1d6 r2junk", "non reconnu"),
    ("gb 3blabla", "non reconnu"), ("wng 3blabla", "non reconnu"),
    ("dh 45blabla", "non reconnu"), ("1d6 t5+1d6", "Ne mélange pas"),
    ("(1d6+2", "parenthèse"), ("1d6 e7", "seuil d'explosion"),
    ("1d6 r7", "seuil de relance"),
])
def test_invalid_expression_is_private_and_consumes_no_randomness(monkeypatch, expression, message):
    draw = Mock()
    monkeypatch.setattr(dice, "_d", draw)
    result, private = roll(expression)
    assert "❌" in result
    assert message in result
    assert private
    draw.assert_not_called()


def test_repeated_expression_rolls_every_dice_group(monkeypatch):
    draw = Mock(side_effect=lambda sides: sides)
    monkeypatch.setattr(dice, "_d", draw)
    result, _private = roll("2 1d1+1d20")
    assert result.count("**21**") == 2
    assert [call.args[0] for call in draw.call_args_list] == [1, 20, 1, 20]


@pytest.mark.parametrize("expression", ["1d1 ir1", "1d1 ie1", "1d6 ir6", "1d6 ie1", "1d6 ir5 ie6"])
def test_impossible_chains_are_rejected_before_rolling(monkeypatch, expression):
    draw = Mock()
    monkeypatch.setattr(dice, "_d", draw)
    output, private = roll(expression)
    assert "impossible à terminer" in output
    assert private
    draw.assert_not_called()


@pytest.mark.parametrize("expression,values,limit,message", [
    ("1d6 ir1", [1, 1, 1], "REROLL_CAP", "relances consécutives"),
    ("1d6 ie6", [6, 6, 6], "EXPLODE_CAP", "explosions en chaîne"),
])
def test_chain_caps_cancel_instead_of_returning_incomplete_values(monkeypatch, expression, values, limit, message):
    monkeypatch.setattr(dice, limit, 2)
    draw = Mock(side_effect=values)
    monkeypatch.setattr(dice, "_d", draw)
    with pytest.raises(RollLimitError, match=message):
        roll(expression)
    assert draw.call_count == 3


@pytest.mark.parametrize("expression,values,limit,expected", [
    ("1d6 ir1", [1, 1, 4], "REROLL_CAP", "**4**"),
    ("1d6 ie6", [6, 6, 2], "EXPLODE_CAP", "**14**"),
])
def test_success_on_the_final_allowed_draw_is_not_rejected(monkeypatch, expression, values, limit, expected):
    monkeypatch.setattr(dice, limit, 2)
    monkeypatch.setattr(dice, "_d", Mock(side_effect=values))
    result, _private = roll(expression)
    assert expected in result
    assert "annulé" not in result


def test_explosion_values_are_listed_once_and_reroll_rules_apply_to_bonus_dice(monkeypatch):
    draw = Mock(side_effect=[6, 1, 2])
    monkeypatch.setattr(dice, "_d", draw)
    result, _private = roll("1d6 e6 r1")
    assert "`[6 2]`" in result
    assert "**8**" in result
    assert "1 dé(s) d'explosion" in result
    assert "+(" not in result
    assert draw.call_count == 3


@pytest.mark.parametrize("flags", ["s", "nr", "ul", "S", "sl"])
def test_display_flags_work_after_complete_expressions(monkeypatch, flags):
    monkeypatch.setattr(dice, "_d", lambda sides: sides)
    result, _private = roll(f"1d1+1d20+2 {flags}")
    assert "**23**" in result
    if flags.lower() != "ul":
        assert "`[" not in result


def test_unrelated_semicolon_rolls_keep_their_results(monkeypatch):
    monkeypatch.setattr(dice, "_d", lambda _sides: 1)
    result, private = roll("1d1+2;1d1 blabla")
    assert "**3**" in result
    assert "❌" in result
    assert not private


def test_deep_parentheses_are_rejected_before_rolling(monkeypatch):
    draw = Mock()
    monkeypatch.setattr(dice, "_d", draw)
    result, _private = roll("(" * 40 + "1d6" + ")" * 40)
    assert "Maximum 32 niveaux" in result
    draw.assert_not_called()


def test_earthdawn_alias_rolls_all_groups_and_preserves_flat_bonus(monkeypatch):
    draw = Mock(side_effect=lambda sides: sides)
    monkeypatch.setattr(dice, "_d", draw)
    result, _private = roll("ed18")
    assert "**25**" in result
    assert [call.args[0] for call in draw.call_args_list] == [10, 8, 6]


def test_cod_threshold_suffix_is_applied(monkeypatch):
    monkeypatch.setattr(dice, "_d", lambda _sides: 8)
    assert "**0** succès" in roll("2cod9")[0]
    assert "**2** succès" in roll("2cod")[0]


@pytest.mark.parametrize("expression,expected", [
    ("2d6+3", "15"), ("1d20-1", "19"), ("4d6*2", "48"), ("10d4/2", "20"),
    ("4d6 k3", "18"), ("4d6 kl2", "12"), ("4d6 d1", "18"), ("4d6 r2", "24"),
    ("4d6 ir2", "24"), ("4d6 e6", "48"), ("5d10 t7", "5"), ("5d10 t7 f1", "5"),
    ("5wod7", "5"), ("sr8", "8"), ("ed7", "12"), ("ed20", "30"), ("age", "18"),
    ("4df", "+4"), ("wng 6", "7"), ("gb 3", "8"), ("3wh45", "0"),
    ("attack +5", "25"), ("skill -2", "18"), ("save +3", "23"),
])
def test_documented_syntax_and_aliases_keep_working(monkeypatch, expression, expected):
    monkeypatch.setattr(dice, "_d", lambda sides: sides)
    result, _private = roll(expression)
    assert "❌" not in result
    assert f"**{expected}**" in result


def test_advantage_and_disadvantage_keep_the_correct_d20(monkeypatch):
    monkeypatch.setattr(dice, "_d", Mock(side_effect=[1, 20, 1, 20]))
    assert "**20**" in roll("+d20")[0]
    assert "**1**" in roll("-d20")[0]


def test_dndstats_keeps_six_separate_stat_results(monkeypatch):
    draw = Mock(return_value=6)
    monkeypatch.setattr(dice, "_d", draw)
    result, _private = roll("dndstats")
    assert result.count("**18**") == 6
    assert draw.call_count == 24


@pytest.mark.parametrize("expression", ["ed0", "ed51", "ed7e6"])
def test_earthdawn_does_not_silently_change_steps_or_ignore_suffixes(monkeypatch, expression):
    draw = Mock()
    monkeypatch.setattr(dice, "_d", draw)
    result, private = roll(expression)
    assert "❌" in result
    assert private
    draw.assert_not_called()


def test_zero_divisor_from_dice_is_an_explicit_error(monkeypatch):
    monkeypatch.setattr(dice, "_d", lambda _sides: 1)
    result, private = roll("1d6/(1d1-1)")
    assert "Division par zéro" in result
    assert "annulé" in result
    assert private
