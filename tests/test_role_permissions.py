from types import SimpleNamespace

from src.utils.permissions import is_admin


def _member(*, administrator=False, manage_guild=False):
    return SimpleNamespace(
        guild_permissions=SimpleNamespace(
            administrator=administrator,
            manage_guild=manage_guild,
        ),
    )


def test_discord_administrator_is_allowed():
    assert is_admin(_member(administrator=True))


def test_manage_server_is_allowed():
    assert is_admin(_member(manage_guild=True))


def test_member_without_management_permission_is_rejected():
    assert not is_admin(_member())
