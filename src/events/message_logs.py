"""Send raw message edits and deletions to each guild's general log channel."""

import logging

import discord

from src.config import GUILD_IDS
from src.utils.db import get_db_connection
from src.utils.message_logs import MessageSnapshot, build_bulk_log, build_message_log


logger = logging.getLogger(__name__)


async def get_logs_channel(bot, guild_id: int):
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "SELECT value FROM guild_config WHERE guild_id = %s AND config_key = 'logs_channel'",
                (guild_id,),
            )
            row = await cursor.fetchone()
    finally:
        db.close()
    if not row:
        return None
    try:
        channel_id = int(row[0])
    except (ValueError, TypeError):
        logger.warning("Invalid general log channel configuration guild=%s", guild_id)
        return None
    guild = bot.get_guild(guild_id)
    return guild.get_channel(channel_id) if guild else None


async def send_log(channel, embed: discord.Embed, file: discord.File | None):
    kwargs = {"embed": embed, "allowed_mentions": discord.AllowedMentions.none()}
    try:
        if file is not None:
            try:
                await channel.send(**kwargs, file=file)
                return
            except discord.Forbidden:
                embed.description = (embed.description or "") + (
                    "\n⚠️ Fichier intégral non envoyé : envoi refusé par Discord. "
                    "Vérifiez notamment la permission « Joindre des fichiers »."
                )
        await channel.send(**kwargs)
    except discord.HTTPException as exc:
        logger.warning("Message log delivery failed channel=%s: %s", channel.id, exc)
    finally:
        if file is not None:
            file.close()
            file.fp.close()


async def register(bot):
    def is_own_message(snapshot: MessageSnapshot) -> bool:
        return bot.user is not None and snapshot.author_id == bot.user.id

    @bot.listen("on_raw_message_delete")
    async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
        if payload.guild_id not in GUILD_IDS:
            return
        before = MessageSnapshot.from_message(payload.cached_message) if payload.cached_message else MessageSnapshot()
        if is_own_message(before):
            return
        channel = await get_logs_channel(bot, payload.guild_id)
        if channel is not None:
            await send_log(channel, *build_message_log(
                payload.guild_id, payload.channel_id, payload.message_id, before,
            ))

    @bot.listen("on_raw_message_edit")
    async def on_raw_message_edit(payload: discord.RawMessageUpdateEvent):
        if payload.guild_id not in GUILD_IDS:
            return
        # Link preview, pin and other metadata updates are not content edits.
        if not {"content", "attachments"}.intersection(payload.data):
            return
        before = MessageSnapshot.from_message(payload.cached_message) if payload.cached_message else MessageSnapshot()
        after = MessageSnapshot.from_update(payload.data, before)
        if is_own_message(after):
            return
        if before.content == after.content and before.attachments == after.attachments:
            return
        channel = await get_logs_channel(bot, payload.guild_id)
        if channel is not None:
            await send_log(channel, *build_message_log(
                payload.guild_id, payload.channel_id, payload.message_id, before, after,
            ))

    @bot.listen("on_raw_bulk_message_delete")
    async def on_raw_bulk_message_delete(payload: discord.RawBulkMessageDeleteEvent):
        if payload.guild_id not in GUILD_IDS:
            return
        snapshots = {
            message.id: MessageSnapshot.from_message(message)
            for message in payload.cached_messages
        }
        own_ids = {message_id for message_id, snapshot in snapshots.items() if is_own_message(snapshot)}
        message_ids = payload.message_ids - own_ids
        if not message_ids:
            return
        snapshots = {message_id: snapshot for message_id, snapshot in snapshots.items() if message_id in message_ids}
        channel = await get_logs_channel(bot, payload.guild_id)
        if channel is not None:
            await send_log(channel, *build_bulk_log(payload.guild_id, payload.channel_id, message_ids, snapshots))
