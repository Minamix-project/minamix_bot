"""Shared access rules for bot commands."""

import discord
from discord import app_commands

from src.utils.rp import RP_ALLOWED_ROLES


def is_admin(member: discord.abc.User) -> bool:
    """Return true for Administrator or Manage Server members."""
    permissions = getattr(member, "guild_permissions", None)
    return bool(
        permissions
        and (permissions.administrator or permissions.manage_guild)
    )


def is_rp_manager(member: discord.abc.User) -> bool:
    """Allow bot admins and configured RP roles to manage roleplay."""
    if is_admin(member):
        return True
    return any(role.id in RP_ALLOWED_ROLES for role in getattr(member, "roles", ()))


def admin_only():
    """Mark a command as admin-only in Discord and enforce it in the bot."""
    def decorator(func):
        func = app_commands.default_permissions(manage_guild=True)(func)
        return app_commands.check(lambda interaction: is_admin(interaction.user))(func)
    return decorator


def rp_only():
    """Enforce access for configured RP managers."""
    return app_commands.check(lambda interaction: is_rp_manager(interaction.user))


ADMIN_COMMANDS = frozenset({"addantispam", "additem", "addmoney", "addnax", "backupstatus", "config", "economystats", "edititem", "giveitem", "listantispam", "removeantispam", "removeitem", "removemoney", "removenax", "resetbalances", "setafklogs", "setlogs", "setrpchannel", "setwarnlogs", "servers", "warn", "warnings", "delwarn", "activity", "absents", "health", "economyconfig", "addecoignore", "removeecoignore", "listecoignore", "audit", "seterrorlogs"})
RP_MANAGER_COMMANDS = frozenset({"rpcreate", "rpdelete", "rpedit", "rpimage"})
