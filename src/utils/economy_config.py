"""Per-guild economy configuration (/economyconfig)."""

import time

from src.utils.db import get_db_connection

DEFAULTS = {
    "work_gain_min": 50,
    "work_gain_max": 250,
    "work_cooldown_seconds": 604800,
    "message_gain_min": 15,
    "message_gain_max": 25,
    "message_gain_long_min": 30,
    "message_gain_long_max": 50,
    "starting_balance": 0,
    "balance_cap": None,
}

_COLUMNS = list(DEFAULTS.keys())
_CACHE_TTL = 60
_cache: dict[int, tuple[float, dict]] = {}


def invalidate_economy_config_cache(guild_id: int) -> None:
    _cache.pop(guild_id, None)


async def get_guild_economy_config(guild_id: int) -> dict:
    cached = _cache.get(guild_id)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM guild_economy_config WHERE guild_id = %s",
                (guild_id,),
            )
            row = await cursor.fetchone()
    finally:
        db.close()

    config = dict(DEFAULTS)
    if row:
        config.update(zip(_COLUMNS, row))

    _cache[guild_id] = (time.time(), config)
    return config


async def update_guild_economy_config(guild_id: int, **changes) -> dict:
    """Update only the provided fields (others are left unchanged)."""
    unknown = set(changes) - set(_COLUMNS)
    if unknown:
        raise ValueError(f"Unknown configuration fields: {unknown}")

    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO guild_economy_config (guild_id) VALUES (%s) "
                "ON DUPLICATE KEY UPDATE guild_id = VALUES(guild_id)",
                (guild_id,),
            )
            if changes:
                set_clause = ", ".join(f"{col} = %s" for col in changes)
                await cursor.execute(
                    f"UPDATE guild_economy_config SET {set_clause} WHERE guild_id = %s",
                    (*changes.values(), guild_id),
                )
        await db.commit()
    finally:
        db.close()

    invalidate_economy_config_cache(guild_id)
    return await get_guild_economy_config(guild_id)
