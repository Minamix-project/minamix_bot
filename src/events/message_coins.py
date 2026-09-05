import time
import random
import logging
import discord
from discord import Message
from src.utils.wallet import modify_user_balance
from src.utils.reactions import handle as _react
from src.utils.economy_config import get_guild_economy_config
from src.config import GUILD_IDS

_last_gain: dict[tuple[int, int], float] = {}
_last_content: dict[tuple[int, int], str] = {}
_last_seen_update: dict[tuple[int, int], float] = {}
COOLDOWN = 60
SEEN_DEBOUNCE = 300
MIN_LENGTH = 5
logger = logging.getLogger(__name__)

_ignored_channels_cache: dict[int, tuple[float, set[int]]] = {}
_IGNORED_CACHE_TTL = 60


def _is_low_effort(content: str) -> bool:
    """Repetitive/spammy content: a single repeated character, or a single repeated word."""
    stripped = content.strip()
    if not stripped:
        return True
    letters_only = stripped.replace(" ", "")
    if letters_only and len(set(letters_only)) == 1:
        return True
    words = stripped.split()
    if len(words) >= 3 and len(set(words)) == 1:
        return True
    return False


async def _get_ignored_channels(guild_id: int) -> set[int]:
    cached = _ignored_channels_cache.get(guild_id)
    if cached and time.time() - cached[0] < _IGNORED_CACHE_TTL:
        return cached[1]

    from src.utils.db import get_db_connection
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "SELECT channel_id FROM guild_economy_ignored_channels WHERE guild_id = %s",
                (guild_id,),
            )
            channels = {row[0] for row in await cursor.fetchall()}
    finally:
        db.close()

    _ignored_channels_cache[guild_id] = (time.time(), channels)
    return channels


def invalidate_ignored_channels_cache(guild_id: int) -> None:
    _ignored_channels_cache.pop(guild_id, None)


async def register(bot):
    @bot.listen("on_message")
    async def on_message_coins(message: Message):
        if message.author.bot or message.webhook_id is not None:
            return

        if message.guild is None or message.guild.id not in GUILD_IDS:
            return

        if bot.user in message.mentions:
            from datetime import datetime
            from src.utils.reactions import _mark_found
            now_time = datetime.now().time()
            if 1 <= now_time.hour < 5:
                await _mark_found(message.author.id, "l_insomniaque")
                await message.reply("T'as vraiment que ça à faire à cette heure-ci ?")
            else:
                await message.reply("Tu veux quoi toi ?")
            return

        await _react(message)

        now = time.time()

        # Update last_seen (debounced every 5 min)
        activity_key = (message.guild.id, message.author.id)
        if now - _last_seen_update.get(activity_key, 0) >= SEEN_DEBOUNCE:
            _last_seen_update[activity_key] = now
            db = None
            try:
                from src.utils.db import get_db_connection
                db = await get_db_connection()
                async with db.cursor() as cursor:
                    await cursor.execute(
                        "INSERT INTO guild_member_activity (guild_id, user_id, last_seen) VALUES (%s, %s, NOW()) "
                        "ON DUPLICATE KEY UPDATE last_seen = NOW()",
                        (message.guild.id, message.author.id),
                    )
                await db.commit()
            except Exception:
                logger.exception("Impossible de mettre à jour l'activité de guild=%s user=%s", message.guild.id, message.author.id)
            finally:
                if db is not None:
                    db.close()

        key = (message.guild.id, message.author.id)

        if now - _last_gain.get(key, 0) < COOLDOWN:
            return

        content = message.content or ""
        if len(content.strip()) < MIN_LENGTH:
            return

        if _is_low_effort(content) or content == _last_content.get(key):
            return

        if message.channel.id in await _get_ignored_channels(message.guild.id):
            return

        _last_gain[key] = now
        _last_content[key] = content

        config = await get_guild_economy_config(message.guild.id)
        gain = (
            random.randint(config["message_gain_long_min"], config["message_gain_long_max"])
            if len(content) >= 1000
            else random.randint(config["message_gain_min"], config["message_gain_max"])
        )

        db = None
        try:
            from src.utils.db import get_db_connection
            db = await get_db_connection()
            await modify_user_balance(db, message.guild.id, message.author.id, gain, "add", type_="message")
        except Exception:
            logger.exception("Échec du gain par message guild=%s user=%s", message.guild.id, message.author.id)
        finally:
            if db is not None:
                db.close()
