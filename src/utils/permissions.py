"""Règles d'accès partagées pour les commandes du bot."""

import os
from functools import lru_cache

import discord
from discord import app_commands

from src.utils.rp import RP_ALLOWED_ROLES


@lru_cache(maxsize=1)
def get_bot_admin_role_ids() -> frozenset[int]:
    """Rôles autorisés par BOT_ADMIN_ROLE_IDS (IDs séparés par des virgules)."""
    role_ids = set()
    for raw_id in os.getenv("BOT_ADMIN_ROLE_IDS", "").split(","):
        raw_id = raw_id.strip()
        if not raw_id:
            continue
        try:
            role_ids.add(int(raw_id))
        except ValueError:
            print(f"[PERMS] ID de rôle admin ignoré : {raw_id!r}")
    return frozenset(role_ids)


def is_admin(member: discord.abc.User) -> bool:
    """True pour un admin Discord ou un rôle administrateur du bot."""
    permissions = getattr(member, "guild_permissions", None)
    if permissions and permissions.administrator:
        return True
    allowed_roles = get_bot_admin_role_ids()
    return any(role.id in allowed_roles for role in getattr(member, "roles", ()))


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


ADMIN_COMMANDS = frozenset({"addantispam", "additem", "addmoney", "addnax", "backupstatus", "config", "economystats", "edititem", "giveitem", "listantispam", "removeantispam", "removeitem", "removemoney", "removenax", "resetbalances", "setafklogs", "setlogs", "setrpchannel", "setwarnlogs", "servers", "warn", "warnings", "delwarn", "activity", "absents", "health", "economyconfig", "addecoignore", "removeecoignore", "listecoignore", "audit", "seterrorlogs"})
RP_MANAGER_COMMANDS = frozenset({"rpcreate", "rpdelete", "rpedit", "rpimage"})
