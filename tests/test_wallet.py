import asyncio

import pytest
import src.utils.wallet as wallet
from src.utils.wallet import calculate_balance

def test_add_and_remove_balance():
    assert calculate_balance(100, 40, "add") == 140
    assert calculate_balance(100, 40, "remove") == 60

def test_balance_never_negative():
    assert calculate_balance(10, 50, "remove") == 0

def test_unknown_operation():
    with pytest.raises(ValueError):
        calculate_balance(10, 1, "bad")


class _Cursor:
    def __init__(self, *, last_work, balance):
        self.last_work = last_work
        self.balance = balance
        self.queries = []
        self.current_query = ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, query, params=None):
        self.current_query = " ".join(query.split())
        self.queries.append((self.current_query, params))

    async def fetchone(self):
        if "SELECT last_work" in self.current_query:
            return (self.last_work,)
        if "SELECT balance" in self.current_query:
            return (self.balance,)
        raise AssertionError(f"Unexpected fetch for {self.current_query}")


class _Database:
    def __init__(self, cursor):
        self.test_cursor = cursor
        self.begins = 0
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.test_cursor

    async def begin(self):
        self.begins += 1

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _patch_work_dependencies(monkeypatch):
    async def config(_guild_id):
        return {"starting_balance": 0, "balance_cap": None}

    async def transaction(*_args, **_kwargs):
        return None

    monkeypatch.setattr(wallet, "get_guild_economy_config", config)
    monkeypatch.setattr(wallet, "record_transaction", transaction)


def test_work_reward_updates_balance_and_cooldown_in_one_transaction(monkeypatch):
    _patch_work_dependencies(monkeypatch)
    cursor = _Cursor(last_work=0, balance=100)
    db = _Database(cursor)

    result = asyncio.run(wallet.claim_work_reward(db, 1, 2, 50, 1_000, 600))

    assert result == (150, 0, 50)
    assert (db.begins, db.commits, db.rollbacks) == (1, 1, 0)
    queries = [query for query, _params in cursor.queries]
    assert any("SELECT last_work" in query and "FOR UPDATE" in query for query in queries)
    assert any("UPDATE guild_work_cooldowns SET last_work" in query for query in queries)
    assert any("UPDATE guild_wallets SET balance" in query for query in queries)


def test_work_reward_rolls_back_when_cooldown_is_active(monkeypatch):
    _patch_work_dependencies(monkeypatch)
    cursor = _Cursor(last_work=900, balance=100)
    db = _Database(cursor)

    result = asyncio.run(wallet.claim_work_reward(db, 1, 2, 50, 1_000, 600))

    assert result == (None, 500, 0)
    assert (db.begins, db.commits, db.rollbacks) == (1, 0, 1)
    assert not any("SELECT balance" in query for query, _params in cursor.queries)
