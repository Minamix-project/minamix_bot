import pytest
from src.utils.wallet import calculate_balance

def test_add_and_remove_balance():
    assert calculate_balance(100, 40, "add") == 140
    assert calculate_balance(100, 40, "remove") == 60

def test_balance_never_negative():
    assert calculate_balance(10, 50, "remove") == 0

def test_unknown_operation():
    with pytest.raises(ValueError):
        calculate_balance(10, 1, "bad")
