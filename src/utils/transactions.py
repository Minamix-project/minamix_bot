"""Economy transaction history (guild_transactions) — see /transactions."""


async def record_transaction(db, guild_id: int, user_id: int, type_: str, amount: int,
                              balance_after: int, detail: str | None = None) -> None:
    async with db.cursor() as cursor:
        await cursor.execute(
            "INSERT INTO guild_transactions (guild_id, user_id, type, amount, balance_after, detail) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (guild_id, user_id, type_[:30], amount, balance_after, detail[:255] if detail else None),
        )
