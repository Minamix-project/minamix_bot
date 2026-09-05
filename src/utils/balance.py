from src.utils.economy_config import get_guild_economy_config


async def get_user_balance(db, guild_id: int, user_id: int):
    config = await get_guild_economy_config(guild_id)
    async with db.cursor() as cursor:
        await cursor.execute(
            "INSERT INTO guild_wallets (guild_id, user_id, balance) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)",
            (guild_id, user_id, config["starting_balance"]),
        )
        await cursor.execute("SELECT balance FROM guild_wallets WHERE guild_id = %s AND user_id = %s", (guild_id, user_id))
        return (await cursor.fetchone())[0]
