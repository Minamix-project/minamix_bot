from types import SimpleNamespace

from src.utils.permissions import is_admin


def _member(*, administrator=False, manage_guild=False, manage_messages=False):
    return SimpleNamespace(
        guild_permissions=SimpleNamespace(
            administrator=administrator,
            manage_guild=manage_guild,
            manage_messages=manage_messages,
        ),
    )


def test_discord_administrator_is_allowed():
    assert is_admin(_member(administrator=True))


def test_manage_server_is_allowed():
    assert is_admin(_member(manage_guild=True))


def test_member_without_management_permission_is_rejected():
    assert not is_admin(_member())


def test_manage_messages_alone_is_not_administrative_access():
    assert not is_admin(_member(manage_messages=True))
