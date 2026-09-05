from src.utils.db import get_db_connection

async def record_admin_action(guild_id: int, actor_id: int, action: str, detail: str | None = None) -> None:
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            value = f"{action}: {detail}" if detail else action
            await cursor.execute("INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)", (guild_id, actor_id, value[:100]))
    finally:
        db.close()
