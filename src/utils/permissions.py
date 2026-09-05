"""Règles d'accès partagées pour les commandes du bot."""

import discord
from discord import app_commands

from src.utils.rp import RP_ALLOWED_ROLES


def is_admin(member: discord.abc.User) -> bool:
    """True avec Administrateur ou Gérer le serveur."""
    permissions = getattr(member, "guild_permissions", None)
    return bool(
        permissions
        and (permissions.administrator or permissions.manage_guild)
    )


def is_rp_manager(member: discord.abc.User) -> bool:
    """Les admins du bot et les rôles RP configurés peuvent gérer le RP."""
    if is_admin(member):
        return True
    return any(role.id in RP_ALLOWED_ROLES for role in getattr(member, "roles", ()))


def admin_only():
    """Marque une commande comme admin dans Discord et vérifie l'accès côté bot."""
    def decorator(func):
        func = app_commands.default_permissions(manage_guild=True)(func)
        return app_commands.check(lambda interaction: is_admin(interaction.user))(func)
    return decorator


def rp_only():
    """Vérifie l'accès des gestionnaires RP côté bot."""
    return app_commands.check(lambda interaction: is_rp_manager(interaction.user))


ADMIN_COMMANDS = frozenset({"addantispam", "additem", "addmoney", "addnax", "backupstatus", "config", "economystats", "edititem", "giveitem", "listantispam", "removeantispam", "removeitem", "removemoney", "removenax", "resetbalances", "setafklogs", "setlogs", "setrpchannel", "setwarnlogs", "servers", "warn", "warnings", "delwarn", "activity", "absents", "health", "economyconfig", "addecoignore", "removeecoignore", "listecoignore", "audit", "seterrorlogs"})
RP_MANAGER_COMMANDS = frozenset({"rpcreate", "rpdelete", "rpedit", "rpimage"})
