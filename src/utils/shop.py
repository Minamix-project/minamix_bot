from src.utils.db import get_db_connection


async def get_shop_items(guild_id: int):
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute("SELECT id, role_id, prix, nom, description, exclusif FROM guild_boutique_roles WHERE guild_id = %s ORDER BY exclusif ASC, id ASC", (guild_id,))
            return (await cursor.fetchall())
    finally:
        db.close()
