from src.utils.db import get_db_connection

async def record_admin_action(guild_id: int, actor_id: int, action: str) -> None:
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute("INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)", (guild_id, actor_id, action[:100]))
    finally:
        db.close()
