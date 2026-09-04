"""Règles d'accès partagées pour les commandes du bot."""

import os

import discord
from discord import app_commands

from src.utils.rp import RP_ALLOWED_ROLES


_DEFAULT_DEVELOPER_IDS = {840870799064956930}


def _developer_ids() -> set[int]:
    configured = os.getenv("DEVELOPER_USER_IDS", "")
    ids = set(_DEFAULT_DEVELOPER_IDS)
    for value in configured.split(","):
        value = value.strip()
        if value.isdigit():
            ids.add(int(value))
    return ids


def is_admin(member: discord.abc.User) -> bool:
    """True pour un administrateur Discord ou un développeur déclaré."""
    if member.id in _developer_ids():
        return True
    permissions = getattr(member, "guild_permissions", None)
    return bool(permissions and permissions.administrator)


def is_rp_manager(member: discord.abc.User) -> bool:
    """Les admins du bot et les rôles RP configurés peuvent gérer le RP."""
    if is_admin(member):
        return True
    return any(role.id in RP_ALLOWED_ROLES for role in getattr(member, "roles", ()))


def admin_only():
    """Marque une commande comme admin dans Discord et vérifie l'accès côté bot."""
    def decorator(func):
        func = app_commands.default_permissions(administrator=True)(func)
        return app_commands.check(lambda interaction: is_admin(interaction.user))(func)
    return decorator


def rp_only():
    """Vérifie l'accès des gestionnaires RP côté bot."""
    return app_commands.check(lambda interaction: is_rp_manager(interaction.user))


ADMIN_COMMANDS = frozenset({"addantispam", "additem", "addmoney", "addnax", "config", "economystats", "edititem", "giveitem", "listantispam", "removeantispam", "removeitem", "removemoney", "removenax", "resetbalances", "setafklogs", "setlogs", "setrpchannel", "setwarnlogs", "servers", "warn", "warnings", "delwarn", "activity", "absents", "health"})
RP_MANAGER_COMMANDS = frozenset({"rpcreate", "rpdelete", "rpedit", "rpimage"})


def configure_command_permissions(bot: discord.Client) -> None:
    """Applique les règles communes avant la synchronisation des commandes."""
    for name in ADMIN_COMMANDS:
        command = bot.tree.get_command(name)
        if command is None:
            print(f"[PERMS] Commande admin introuvable : {name}")
            continue
        command.default_permissions = discord.Permissions(administrator=True)
        command.add_check(lambda interaction: is_admin(interaction.user))

    for name in RP_MANAGER_COMMANDS:
        command = bot.tree.get_command(name)
        if command is None:
            print(f"[PERMS] Commande RP introuvable : {name}")
            continue
        command.add_check(lambda interaction: is_rp_manager(interaction.user))
