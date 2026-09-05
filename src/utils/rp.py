from src.utils.db import get_db_connection

RP_ALLOWED_ROLES = {
    1437105432291315806,
    1437105432291315805,
    1437105432278728784,
    1507492860956774633,
}

# guild_id -> {prefix: (char_id, user_id, name, image_url)}
_prefix_cache: dict[int, dict[str, tuple]] = {}


def has_rp_permission(member) -> bool:
    # Import local pour éviter une dépendance circulaire au chargement.
    from src.utils.permissions import is_rp_manager
    return is_rp_manager(member)


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
