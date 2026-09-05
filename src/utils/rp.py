from urllib.parse import urlsplit, urlunsplit

from src.utils.db import get_db_connection


def normalize_discord_image_url(url: str) -> str:
    """Remove expiring signature parameters from Discord attachment CDN URLs."""
    parts = urlsplit(url)
    if parts.hostname in {"cdn.discordapp.com", "media.discordapp.net"} and parts.path.startswith("/attachments/"):
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return url

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
