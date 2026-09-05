"""Shared access rules for bot commands."""

import discord
from discord import app_commands

def is_admin(member: discord.abc.User) -> bool:
    """Return true for Administrator or Manage Server members."""
    permissions = getattr(member, "guild_permissions", None)
    return bool(
        permissions
        and (permissions.administrator or permissions.manage_guild)
    )


def admin_only():
    """Mark a command as admin-only in Discord and enforce it in the bot."""
    def decorator(func):
        func = app_commands.default_permissions(manage_guild=True)(func)
        return app_commands.check(lambda interaction: is_admin(interaction.user))(func)
    return decorator


ADMIN_COMMANDS = frozenset({"addantispam", "additem", "addmoney", "addnax", "backupstatus", "config", "economystats", "edititem", "giveitem", "listantispam", "removeantispam", "removeitem", "removemoney", "removenax", "resetbalances", "setafklogs", "setlogs", "setrpchannel", "setwarnlogs", "servers", "warn", "warnings", "delwarn", "activity", "absents", "health", "economyconfig", "addecoignore", "removeecoignore", "listecoignore", "audit", "seterrorlogs", "rpcreate", "rpdelete", "rpedit", "rpimage"})
