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
