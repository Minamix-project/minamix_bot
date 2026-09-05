from src.utils.db import get_db_connection


def get_shop_items(guild_id: int):
    db = get_db_connection()
    try:
        with db.cursor() as cursor:
            cursor.execute("SELECT id, role_id, prix, nom, description, exclusif FROM guild_boutique_roles WHERE guild_id = %s ORDER BY exclusif ASC, id ASC", (guild_id,))
            return cursor.fetchall()
    finally:
        db.close()
