"""Validate destinations and restrict reminder mentions to explicitly selected users."""

import re

import discord

from src.utils.reminders import CATEGORIES, Reminder

# Translate failures stored by the first release without rewriting reminder data.
_DELIVERY_ERRORS = {
    "Choose a text channel in this server.": "Choisis un salon textuel de ce serveur.",
    "You must be able to view and send messages in the destination channel.":
        "Tu dois pouvoir voir le salon de destination et y envoyer des messages.",
    "The bot needs View Channel, Send Messages, and Embed Links in the destination.":
        "Le bot doit pouvoir voir le salon, envoyer des messages et intégrer des liens dans le salon de destination.",
    "This server is no longer available.": "Ce serveur n'est plus disponible.",
    "The reminder owner is no longer in this server.": "Le créateur du rappel n'est plus sur ce serveur.",
    "Every selected member must belong to this server and be able to view the channel.":
        "Chaque membre sélectionné doit appartenir à ce serveur et pouvoir voir le salon.",
    "Delivery was interrupted too many times. Edit this reminder to retry.":
        "L'envoi a été interrompu trop de fois. Modifie ce rappel pour réessayer.",
    "Discord denied delivery or the destination was removed.":
        "Discord a refusé l'envoi ou la destination a été supprimée.",
    "Temporary delivery failure. Please try again later.": "Échec temporaire de l'envoi. Réessaie plus tard.",
}


def delivery_error_message(detail: str) -> str:
    if detail in _DELIVERY_ERRORS:
        return _DELIVERY_ERRORS[detail]
    if detail in _DELIVERY_ERRORS.values():
        return detail
    return "L'envoi du rappel a échoué. Vérifie sa destination et les permissions, puis réessaie."


def parse_recipients(value: str) -> tuple[int, ...]:
    if value.strip().lower() in {"aucun", "none"}:
        return ()
    ids = []
    for token in re.split(r"[\s,]+", value.strip()):
        match = re.fullmatch(r"(?:<@!?(\d{1,20})>|(\d{1,20}))", token)
        if not match:
            raise ValueError("Utilise des mentions ou identifiants de membres séparés par des espaces, ou 'aucun'.")
        user_id = int(match[1] or match[2])
        if not 0 < user_id < 2**64:
            raise ValueError("Identifiant de membre invalide.")
        if user_id not in ids:
            ids.append(user_id)
    if len(ids) > 10:
        raise ValueError("Sélectionne au maximum 10 membres supplémentaires.")
    return tuple(ids)


async def resolve_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None


def check_channel(channel, owner: discord.Member, bot_member: discord.Member) -> None:
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != owner.guild.id:
        raise ValueError(delivery_error_message("Choose a text channel in this server."))
    owner_permissions = channel.permissions_for(owner)
    bot_permissions = channel.permissions_for(bot_member)
    if not (owner_permissions.view_channel and owner_permissions.send_messages):
        raise ValueError(delivery_error_message("You must be able to view and send messages in the destination channel."))
    if not (bot_permissions.view_channel and bot_permissions.send_messages and bot_permissions.embed_links):
        raise ValueError(delivery_error_message("The bot needs View Channel, Send Messages, and Embed Links in the destination."))


async def validate_destination(bot: discord.Client, reminder: Reminder) -> None:
    guild = bot.get_guild(reminder.guild_id)
    if guild is None:
        raise ValueError(delivery_error_message("This server is no longer available."))
    owner = await resolve_member(guild, reminder.user_id)
    if owner is None:
        raise ValueError(delivery_error_message("The reminder owner is no longer in this server."))
    if reminder.channel_id is None:
        return
    channel = guild.get_channel(reminder.channel_id)
    if channel is None:
        channel = await bot.fetch_channel(reminder.channel_id)
    check_channel(channel, owner, guild.me)
    for user_id in reminder.recipient_ids:
        member = await resolve_member(guild, user_id)
        if member is None or not channel.permissions_for(member).view_channel:
            raise ValueError(delivery_error_message("Every selected member must belong to this server and be able to view the channel."))


async def send_reminder(bot: discord.Client, reminder: Reminder) -> None:
    # Recheck permissions at delivery time: scheduled messages must not bypass
    # access changes that happened after creation.
    await validate_destination(bot, reminder)
    guild = bot.get_guild(reminder.guild_id)
    owner = await resolve_member(guild, reminder.user_id)
    target = owner if reminder.channel_id is None else guild.get_channel(reminder.channel_id)
    if target is None:
        target = await bot.fetch_channel(reminder.channel_id)
    ids = list(reminder.recipient_ids)
    if reminder.mention_owner and reminder.user_id not in ids:
        ids.insert(0, reminder.user_id)
    embed = discord.Embed(
        title=f"⏰ {CATEGORIES[reminder.category]}",
        description=reminder.message,
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Prévu pour le", value=f"<t:{reminder.due_at}:F>")
    embed.set_footer(text=f"Rappel #{reminder.id} · Créé par {owner.display_name}")
    await target.send(
        content=" ".join(f"<@{user_id}>" for user_id in ids) or None,
        embed=embed,
        allowed_mentions=discord.AllowedMentions(
            everyone=False, roles=False, users=[discord.Object(id=user_id) for user_id in ids], replied_user=False,
        ),
    )
