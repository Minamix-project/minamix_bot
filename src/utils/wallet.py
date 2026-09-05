import pymysql


def calculate_balance(current: int, amount: int, operation: str) -> int:
    if operation == "add": return current + amount
    if operation == "remove": return max(current - amount, 0)
    if operation == "set": return amount
    raise ValueError(f"Opération inconnue : {operation}")


async def modify_user_balance(db: pymysql.connections.Connection, guild_id: int, user_id: int, amount: int, operation: str = "add") -> int:
    with db.cursor() as cursor:
        cursor.execute("INSERT INTO guild_wallets (guild_id, user_id, balance) VALUES (%s, %s, 0) ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)", (guild_id, user_id))
        cursor.execute("SELECT balance FROM guild_wallets WHERE guild_id = %s AND user_id = %s FOR UPDATE", (guild_id, user_id))
        current = cursor.fetchone()[0]
        value = calculate_balance(current, amount, operation)
        cursor.execute("UPDATE guild_wallets SET balance = %s WHERE guild_id = %s AND user_id = %s", (value, guild_id, user_id))
        return value
