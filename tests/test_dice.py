from src.utils.dice import roll

def test_basic_roll():
    result = roll("1d6")
    assert "d6" in result[0]

def test_rejects_too_many_dice():
    result, _private = roll("201d6")
    assert "Maximum 200 dés" in result
