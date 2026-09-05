async def get_user_balance(db, guild_id: int, user_id: int):
    with db.cursor() as cursor:
        cursor.execute("INSERT INTO guild_wallets (guild_id, user_id, balance) VALUES (%s, %s, 0) ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)", (guild_id, user_id))
        cursor.execute("SELECT balance FROM guild_wallets WHERE guild_id = %s AND user_id = %s", (guild_id, user_id))
        return cursor.fetchone()[0]
