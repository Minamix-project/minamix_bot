from src.utils.db import get_db_connection


def _format_admin_action(action, detail):
    return (f"{action}: {detail}" if detail else action)[:100]


async def write_admin_actions(cursor, guild_id, actor_id, actions):
    """Append audit entries using the caller's transaction."""
    await cursor.executemany(
        "INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)",
        [(guild_id, actor_id, _format_admin_action(action, detail)) for action, detail in actions],
    )


async def record_admin_action(guild_id: int, actor_id: int, action: str, detail: str | None = None) -> None:
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)",
                (guild_id, actor_id, _format_admin_action(action, detail)),
            )
    finally:
        db.close()
