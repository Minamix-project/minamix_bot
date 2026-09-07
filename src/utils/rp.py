import json
from urllib.parse import urlsplit, urlunsplit

from src.utils.db import get_db_connection


def normalize_discord_image_url(url: str) -> str:
    """Remove expiring signature parameters from Discord attachment CDN URLs."""
    parts = urlsplit(url)
    if parts.hostname in {"cdn.discordapp.com", "media.discordapp.net"} and parts.path.startswith("/attachments/"):
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return url


def image_url_from_message(message, fallback: str | None = None) -> str | None:
    """Extract the permanent image URL from an uploaded RP sheet message."""
    for attachment in getattr(message, "attachments", ()):
        if getattr(attachment, "content_type", "").startswith("image/"):
            return normalize_discord_image_url(attachment.url)
    for embed in getattr(message, "embeds", ()):
        image = getattr(embed, "image", None)
        url = getattr(image, "url", None)
        if url:
            return normalize_discord_image_url(url)
    if fallback and "/ephemeral-attachments/" not in fallback:
        return normalize_discord_image_url(fallback)
    return None


def prefixes_too_close(candidate: str, existing: str) -> bool:
    """Reject visually ambiguous prefixes without imposing a fixed naming style."""
    left = candidate.strip().casefold().rstrip(" :!?-_·")
    right = existing.strip().casefold().rstrip(" :!?-_·")
    if not left or not right:
        return False
    return left == right or (left.startswith(right) or right.startswith(left)) and abs(len(left) - len(right)) <= 1

# guild_id -> {prefix: (char_id, user_id, name, image_url)}
_prefix_cache: dict[int, dict[str, tuple]] = {}


async def get_prefix_cache(guild_id: int) -> dict[str, tuple]:
    if guild_id not in _prefix_cache:
        await _load_cache(guild_id)
    return _prefix_cache[guild_id]


async def is_rp_maintenance_enabled(guild_id: int) -> bool:
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "SELECT value FROM guild_config WHERE guild_id = %s AND config_key = 'rp_maintenance'",
                (guild_id,),
            )
            row = await cursor.fetchone()
            return bool(row and row[0] == "1")
    finally:
        db.close()


async def claim_rp_cooldown(guild_id: int, user_id: int, character_id: int, now: int, cooldown: int = 3) -> bool:
    db = await get_db_connection()
    try:
        await db.begin()
        async with db.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO rp_message_cooldowns (guild_id, user_id, character_id, last_sent) VALUES (%s, %s, %s, 0) "
                "ON DUPLICATE KEY UPDATE character_id = VALUES(character_id)",
                (guild_id, user_id, character_id),
            )
            await cursor.execute(
                "SELECT last_sent FROM rp_message_cooldowns WHERE guild_id = %s AND user_id = %s AND character_id = %s FOR UPDATE",
                (guild_id, user_id, character_id),
            )
            last_sent = (await cursor.fetchone())[0]
            if last_sent and now - last_sent < cooldown:
                await db.rollback()
                return False
            await cursor.execute(
                "UPDATE rp_message_cooldowns SET last_sent = %s WHERE guild_id = %s AND user_id = %s AND character_id = %s",
                (now, guild_id, user_id, character_id),
            )
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        raise
    finally:
        db.close()


async def record_character_history(cursor, *, character_id: int | None, guild_id: int, actor_id: int, action: str, snapshot: dict) -> None:
    await cursor.execute(
        "INSERT INTO rp_character_history (character_id, guild_id, actor_id, action, snapshot) VALUES (%s, %s, %s, %s, %s)",
        (character_id, guild_id, actor_id, action, json.dumps(snapshot, ensure_ascii=False)),
    )


async def _load_cache(guild_id: int) -> None:
    db = await get_db_connection()
    cursor = await db.cursor()
    await cursor.execute(
        "SELECT id, user_id, name, image_url, prefix FROM rp_characters WHERE guild_id = %s",
        (guild_id,)
    )
    rows = (await cursor.fetchall())
    await cursor.close()
    db.close()
    _prefix_cache[guild_id] = {
        row[4]: (row[0], row[1], row[2], row[3]) for row in rows
    }


def invalidate_cache(guild_id: int) -> None:
    _prefix_cache.pop(guild_id, None)
