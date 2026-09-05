from src.utils.economy_config import get_guild_economy_config
from src.utils.transactions import record_transaction


def calculate_balance(current: int, amount: int, operation: str, cap: int | None = None) -> int:
    if operation == "add":
        value = current + amount
        return min(value, cap) if cap is not None else value
    if operation == "remove": return max(current - amount, 0)
    if operation == "set": return amount
    raise ValueError(f"Opération inconnue : {operation}")


async def modify_user_balance(db, guild_id: int, user_id: int, amount: int, operation: str = "add",
                               *, type_: str | None = None, detail: str | None = None) -> int:
    config = await get_guild_economy_config(guild_id)
    await db.begin()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO guild_wallets (guild_id, user_id, balance) VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)",
                (guild_id, user_id, config["starting_balance"]),
            )
            await cursor.execute("SELECT balance FROM guild_wallets WHERE guild_id = %s AND user_id = %s FOR UPDATE", (guild_id, user_id))
            current = (await cursor.fetchone())[0]
            value = calculate_balance(current, amount, operation, config["balance_cap"])
            await cursor.execute("UPDATE guild_wallets SET balance = %s WHERE guild_id = %s AND user_id = %s", (value, guild_id, user_id))
            if type_ is not None:
                signed_amount = value - current
                await record_transaction(db, guild_id, user_id, type_, signed_amount, value, detail)
        await db.commit()
        return value
    except Exception:
        await db.rollback()
        raise


async def claim_work_reward(
    db, guild_id: int, user_id: int, gain: int, now: int, cooldown: int
) -> tuple[int | None, int, int]:
    """Claim a work reward and update its cooldown in one transaction."""
    config = await get_guild_economy_config(guild_id)
    await db.begin()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO guild_work_cooldowns (guild_id, user_id, last_work) "
                "VALUES (%s, %s, 0) ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)",
                (guild_id, user_id),
            )
            await cursor.execute(
                "SELECT last_work FROM guild_work_cooldowns "
                "WHERE guild_id = %s AND user_id = %s FOR UPDATE",
                (guild_id, user_id),
            )
            last_work = (await cursor.fetchone())[0]
            elapsed = now - last_work
            if last_work and elapsed < cooldown:
                await db.rollback()
                return None, cooldown - elapsed, 0

            await cursor.execute(
                "INSERT INTO guild_wallets (guild_id, user_id, balance) VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)",
                (guild_id, user_id, config["starting_balance"]),
            )
            await cursor.execute(
                "SELECT balance FROM guild_wallets WHERE guild_id = %s AND user_id = %s FOR UPDATE",
                (guild_id, user_id),
            )
            current = (await cursor.fetchone())[0]
            value = calculate_balance(current, gain, "add", config["balance_cap"])
            await cursor.execute(
                "UPDATE guild_wallets SET balance = %s WHERE guild_id = %s AND user_id = %s",
                (value, guild_id, user_id),
            )
            await cursor.execute(
                "UPDATE guild_work_cooldowns SET last_work = %s WHERE guild_id = %s AND user_id = %s",
                (now, guild_id, user_id),
            )
            await record_transaction(db, guild_id, user_id, "work", value - current, value)
        await db.commit()
        return value, 0, value - current
    except Exception:
        await db.rollback()
        raise
