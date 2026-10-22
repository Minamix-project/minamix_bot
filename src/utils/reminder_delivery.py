"""Validate destinations and restrict reminder mentions to explicitly selected users."""

import re

import discord

from src.utils.reminders import CATEGORIES, Reminder


def parse_recipients(value: str) -> tuple[int, ...]:
    if value.strip().lower() == "none":
        return ()
    ids = []
    for token in re.split(r"[\s,]+", value.strip()):
        match = re.fullmatch(r"(?:<@!?(\d{1,20})>|(\d{1,20}))", token)
        if not match:
            raise ValueError("Use member mentions or IDs separated by spaces, or 'none' to clear them.")
        user_id = int(match[1] or match[2])
        if not 0 < user_id < 2**64:
            raise ValueError("Invalid member ID.")
        if user_id not in ids:
            ids.append(user_id)
    if len(ids) > 10:
        raise ValueError("Select at most 10 additional members.")
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
        raise ValueError("Choose a text channel in this server.")
    owner_permissions = channel.permissions_for(owner)
    bot_permissions = channel.permissions_for(bot_member)
    if not (owner_permissions.view_channel and owner_permissions.send_messages):
        raise ValueError("You must be able to view and send messages in the destination channel.")
    if not (bot_permissions.view_channel and bot_permissions.send_messages and bot_permissions.embed_links):
        raise ValueError("The bot needs View Channel, Send Messages, and Embed Links in the destination.")


async def validate_destination(bot: discord.Client, reminder: Reminder) -> None:
    guild = bot.get_guild(reminder.guild_id)
    if guild is None:
        raise ValueError("This server is no longer available.")
    owner = await resolve_member(guild, reminder.user_id)
    if owner is None:
        raise ValueError("The reminder owner is no longer in this server.")
    if reminder.channel_id is None:
        return
    channel = guild.get_channel(reminder.channel_id)
    if channel is None:
        channel = await bot.fetch_channel(reminder.channel_id)
    check_channel(channel, owner, guild.me)
    for user_id in reminder.recipient_ids:
        member = await resolve_member(guild, user_id)
        if member is None or not channel.permissions_for(member).view_channel:
            raise ValueError("Every selected member must belong to this server and be able to view the channel.")


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
    embed.add_field(name="Scheduled for", value=f"<t:{reminder.due_at}:F>")
    embed.set_footer(text=f"Reminder #{reminder.id} · Created by {owner.display_name}")
    await target.send(
        content=" ".join(f"<@{user_id}>" for user_id in ids) or None,
        embed=embed,
        allowed_mentions=discord.AllowedMentions(
            everyone=False, roles=False, users=[discord.Object(id=user_id) for user_id in ids], replied_user=False,
        ),
    )
