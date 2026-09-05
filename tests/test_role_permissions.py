from types import SimpleNamespace

from src.utils.permissions import get_bot_admin_role_ids, is_admin


def _member(*, administrator=False, role_ids=()):
    return SimpleNamespace(
        guild_permissions=SimpleNamespace(administrator=administrator),
        roles=[SimpleNamespace(id=role_id) for role_id in role_ids],
    )


def test_discord_administrator_is_allowed(monkeypatch):
    monkeypatch.delenv("BOT_ADMIN_ROLE_IDS", raising=False)
    get_bot_admin_role_ids.cache_clear()
    assert is_admin(_member(administrator=True))


def test_configured_bot_admin_role_is_allowed(monkeypatch):
    monkeypatch.setenv("BOT_ADMIN_ROLE_IDS", "123, 456")
    get_bot_admin_role_ids.cache_clear()
    assert is_admin(_member(role_ids=(456,)))
    assert not is_admin(_member(role_ids=(789,)))


def test_invalid_role_ids_are_ignored(monkeypatch):
    monkeypatch.setenv("BOT_ADMIN_ROLE_IDS", "123,invalid,")
    get_bot_admin_role_ids.cache_clear()
    assert get_bot_admin_role_ids() == frozenset({123})
