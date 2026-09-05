"""Technical error notifications to a private channel, without exposing sensitive details."""

import secrets
import logging

import discord

from src.utils.db import get_db_connection

logger = logging.getLogger(__name__)


async def _get_error_logs_channel(bot: discord.Client, guild_id: int):
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "SELECT value FROM guild_config WHERE guild_id = %s AND config_key = 'error_logs_channel'",
                (guild_id,),
            )
            row = await cursor.fetchone()
    finally:
        db.close()
    if not row:
        return None
    return bot.get_channel(int(row[0]))


async def _notify_channel(bot: discord.Client, guild_id: int, ref: str, source: str,
                           error: BaseException, user: discord.abc.User | None) -> None:
    channel = await _get_error_logs_channel(bot, guild_id)
    if channel is None:
        return

    embed = discord.Embed(title="⚠️ Erreur technique", color=discord.Color.red())
    embed.add_field(name="Référence", value=f"`{ref}`", inline=True)
    embed.add_field(name="Type", value=f"`{error.__class__.__name__}`", inline=True)
    embed.add_field(name="Source", value=f"`{source}`", inline=False)
    if user is not None:
        embed.add_field(name="Utilisateur", value=f"{user} (`{user.id}`)", inline=False)
    embed.timestamp = discord.utils.utcnow()

    try:
        await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


async def report_error(bot: discord.Client, *, guild_ids, source: str, error: BaseException,
                        user: discord.abc.User | None = None) -> str:
    """Log the full error to the console once, notify the error channel(s)
    (no traceback or sensitive detail), return a short reference to give to the user."""
    ref = secrets.token_hex(4)
    logger.error(
        "Erreur %s dans %s", ref, source,
        exc_info=(type(error), error, error.__traceback__),
    )

    if isinstance(guild_ids, int):
        guild_ids = [guild_ids]
    for guild_id in guild_ids or ():
        try:
            await _notify_channel(bot, guild_id, ref, source, error, user)
        except Exception:
            logger.exception("Could not send error %s to guild %s", ref, guild_id)

    return ref
