"""Ticket log embeds following the bot's existing moderation log presentation."""

import discord

from src.utils.message_logs import base_embed
from src.utils.tickets import CATEGORIES


ACTION_STYLES = {
    "created": ("🎫 Ticket créé", discord.Color.green()),
    "closed": ("🔒 Ticket fermé", discord.Color.red()),
    "reopened": ("🔓 Ticket rouvert", discord.Color.green()),
    "added": ("👤 Membre ajouté au ticket", discord.Color.green()),
    "removed": ("👤 Membre retiré du ticket", discord.Color.orange()),
    "renamed": ("✏️ Ticket renommé", discord.Color.orange()),
    "linked": ("🔗 Utilisateur lié au ticket", discord.Color.blurple()),
}


def user_text(guild, user_id):
    member = guild.get_member(user_id)
    name = discord.utils.escape_markdown(member.display_name) + " · " if member else ""
    return f"{name}<@{user_id}> (`{user_id}`)"


def build_ticket_log(guild, ticket, action, actor_id, *, detail=None):
    title, color = ACTION_STYLES[action]
    embed = base_embed(title, color, ticket.channel_id)
    embed.add_field(name="Ticket", value=f"#{ticket.reference}")
    embed.add_field(name="Catégorie", value=CATEGORIES[ticket.category])
    embed.add_field(name="Créateur", value=user_text(guild, ticket.creator_id), inline=False)
    embed.add_field(name="Par", value=user_text(guild, actor_id), inline=False)
    if detail and action in {"added", "removed", "linked"}:
        label = "Utilisateur concerné" if action == "linked" else "Membre concerné"
        embed.add_field(name=label, value=user_text(guild, int(detail)), inline=False)
    elif detail and action == "renamed":
        embed.add_field(name="Nouveau nom", value=discord.utils.escape_markdown(detail), inline=False)
    creator = guild.get_member(ticket.creator_id)
    if creator:
        embed.set_thumbnail(url=creator.display_avatar.url)
    bot_user = guild.me
    embed.set_footer(text=bot_user.name, icon_url=bot_user.display_avatar.url)
    return embed
