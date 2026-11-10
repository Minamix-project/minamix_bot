"""Single route for privileged message deletion and existing RP-owner reactions."""

from src.config import GUILD_IDS
from src.utils.error_reporting import report_error

import discord


REACTION_DELETE_USER_ID = 840870799064956930
DELETE_EMOJI = "❌"


async def handle_delete_reaction(bot, payload, rp_messages):
    if payload.guild_id not in GUILD_IDS or str(payload.emoji) != DELETE_EMOJI:
        return False
    rp_entry = rp_messages.get(payload.message_id)
    if payload.user_id != REACTION_DELETE_USER_ID and (rp_entry is None or payload.user_id != rp_entry[0]):
        return False
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return False
    try:
        channel = bot.get_channel(payload.channel_id)
        if channel is None:
            channel = await bot.fetch_channel(payload.channel_id)
        if getattr(getattr(channel, "guild", None), "id", None) != payload.guild_id:
            return False
        message = await channel.fetch_message(payload.message_id)
        await message.delete()
    except discord.NotFound:
        # Another moderator or feature may already have deleted the message.
        rp_messages.pop(payload.message_id, None)
        return False
    except discord.HTTPException as error:
        # Keep RP ownership on failure so a retry remains possible.
        member = getattr(payload, "member", None) or guild.get_member(payload.user_id)
        await report_error(bot, guild_ids=payload.guild_id, source="reaction_delete", error=error, user=member)
        return False
    rp_messages.pop(payload.message_id, None)
    return True
