from src.utils.format import format_amount

def test_format_amount():
    assert format_amount(999) == "999"
    assert format_amount(1500) == "1.5K"
    assert format_amount(2_000_000) == "2M"
