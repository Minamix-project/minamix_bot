import pytest
from src.utils.dice import ParseError, roll

def test_basic_roll():
    result = roll("1d6")
    assert "d6" in result[0]

def test_rejects_too_many_dice():
    with pytest.raises(ParseError):
        roll("201d6")
