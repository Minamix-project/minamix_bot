from src.utils.db import get_db_connection


async def get_shop_items(guild_id: int):
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "SELECT id, role_id, prix, nom, description, exclusif FROM guild_boutique_roles "
                "WHERE guild_id = %s ORDER BY exclusif ASC, id ASC",
                (guild_id,),
            )
            return (await cursor.fetchall())
    finally:
        db.close()


async def get_balance(db, guild_id: int, user_id: int) -> int:
    async with db.cursor() as cursor:
        await cursor.execute(
            "INSERT INTO guild_wallets (guild_id, user_id, balance) VALUES (%s, %s, 0) "
            "ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)",
            (guild_id, user_id),
        )
        await cursor.execute("SELECT balance FROM guild_wallets WHERE guild_id = %s AND user_id = %s", (guild_id, user_id))
        return (await cursor.fetchone())[0]


async def modify_balance(db, guild_id: int, user_id: int, amount: int, operation: str = "add") -> int:
    current = await get_balance(db, guild_id, user_id)
    if operation == "add":
        value = current + amount
    elif operation == "remove":
        value = max(current - amount, 0)
    elif operation == "set":
        value = amount
    else:
        raise ValueError(f"Unknown operation: {operation}")
    async with db.cursor() as cursor:
        await cursor.execute("UPDATE guild_wallets SET balance = %s WHERE guild_id = %s AND user_id = %s", (value, guild_id, user_id))
    return value
