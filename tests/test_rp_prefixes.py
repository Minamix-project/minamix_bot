from src.utils.rp import prefixes_too_close


def test_prefixes_ignore_case_and_trailing_punctuation():
    assert prefixes_too_close("Aria:", "aria")


def test_distinct_prefixes_are_allowed():
    assert not prefixes_too_close("Aria:", "Bran:")
