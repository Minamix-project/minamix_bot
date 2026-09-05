import pytest

from src.config import _integer_set_from_env


def test_integer_set_from_env_uses_defaults(monkeypatch):
    monkeypatch.delenv("TEST_IDS", raising=False)
    assert _integer_set_from_env("TEST_IDS", [1, 2]) == {1, 2}


def test_integer_set_from_env_parses_comma_separated_ids(monkeypatch):
    monkeypatch.setenv("TEST_IDS", "10, 20,10")
    assert _integer_set_from_env("TEST_IDS", []) == {10, 20}


def test_integer_set_from_env_rejects_invalid_ids(monkeypatch):
    monkeypatch.setenv("TEST_IDS", "10,nope")
    with pytest.raises(RuntimeError):
        _integer_set_from_env("TEST_IDS", [])
