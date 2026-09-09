"""Atomic player-to-player transfers for standard money and RP NAX."""

import time

from src.utils.economy_config import get_guild_economy_config
from src.utils.transactions import record_transaction


async def _claim_transfer_limit(cursor, guild_id, sender_id, currency, amount, now, cooldown, daily_limit):
    await cursor.execute("INSERT INTO guild_transfer_daily_totals (guild_id, user_id, currency, transfer_date, amount, last_transfer_at) VALUES (%s, %s, %s, CURDATE(), 0, 0) ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)", (guild_id, sender_id, currency))
    await cursor.execute("SELECT amount, last_transfer_at FROM guild_transfer_daily_totals WHERE guild_id = %s AND user_id = %s AND currency = %s AND transfer_date = CURDATE() FOR UPDATE", (guild_id, sender_id, currency))
    sent_today, last_transfer_at = await cursor.fetchone()
    if cooldown and last_transfer_at and now - last_transfer_at < cooldown:
        return "cooldown"
    if daily_limit and sent_today + amount > daily_limit:
        return "daily_limit"
    await cursor.execute("UPDATE guild_transfer_daily_totals SET amount = amount + %s, last_transfer_at = %s WHERE guild_id = %s AND user_id = %s AND currency = %s AND transfer_date = CURDATE()", (amount, now, guild_id, sender_id, currency))


async def _record_transfer(cursor, guild_id, currency, sender_id, recipient_id, amount, reason, sender_character_id=None, recipient_character_id=None):
    await cursor.execute("INSERT INTO guild_player_transfers (guild_id, currency, sender_id, recipient_id, sender_character_id, recipient_character_id, amount, reason) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (guild_id, currency, sender_id, recipient_id, sender_character_id, recipient_character_id, amount, reason[:255]))


async def transfer_money(db, guild_id, sender_id, recipient_id, amount, reason):
    if amount <= 0 or sender_id == recipient_id:
        return False, "invalid", None, None
    config, now = await get_guild_economy_config(guild_id), int(time.time())
    await db.begin()
    try:
        async with db.cursor() as cursor:
            status = await _claim_transfer_limit(cursor, guild_id, sender_id, "money", amount, now, config["transfer_cooldown_seconds"], config["transfer_daily_limit"])
            if status:
                await db.rollback()
                return False, status, None, None
            for user_id in sorted((sender_id, recipient_id)):
                await cursor.execute("INSERT INTO guild_wallets (guild_id, user_id, balance) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)", (guild_id, user_id, config["starting_balance"]))
            balances = {}
            for user_id in sorted((sender_id, recipient_id)):
                await cursor.execute("SELECT balance FROM guild_wallets WHERE guild_id = %s AND user_id = %s FOR UPDATE", (guild_id, user_id))
                balances[user_id] = (await cursor.fetchone())[0]
            if balances[sender_id] < amount:
                await db.rollback()
                return False, "insufficient", None, None
            cap = config["balance_cap"]
            if cap is not None and balances[recipient_id] + amount > cap:
                await db.rollback()
                return False, "recipient_cap", None, None
            sender_balance, recipient_balance = balances[sender_id] - amount, balances[recipient_id] + amount
            await cursor.execute("UPDATE guild_wallets SET balance = %s WHERE guild_id = %s AND user_id = %s", (sender_balance, guild_id, sender_id))
            await cursor.execute("UPDATE guild_wallets SET balance = %s WHERE guild_id = %s AND user_id = %s", (recipient_balance, guild_id, recipient_id))
            await record_transaction(db, guild_id, sender_id, "transfer_sent", -amount, sender_balance, reason)
            await record_transaction(db, guild_id, recipient_id, "transfer_received", amount, recipient_balance, reason)
            await _record_transfer(cursor, guild_id, "money", sender_id, recipient_id, amount, reason)
        await db.commit()
        return True, "ok", sender_balance, recipient_balance
    except Exception:
        await db.rollback()
        raise


async def transfer_nax(db, guild_id, sender_id, recipient_id, sender_character_id, recipient_character_id, amount, reason):
    if amount <= 0 or sender_id == recipient_id or sender_character_id == recipient_character_id:
        return False, "invalid", None, None
    config, now = await get_guild_economy_config(guild_id), int(time.time())
    await db.begin()
    try:
        async with db.cursor() as cursor:
            status = await _claim_transfer_limit(cursor, guild_id, sender_id, "nax", amount, now, config["nax_transfer_cooldown_seconds"], config["nax_transfer_daily_limit"])
            if status:
                await db.rollback()
                return False, status, None, None
            characters = {}
            for character_id in sorted((sender_character_id, recipient_character_id)):
                await cursor.execute("SELECT user_id, nax_balance FROM rp_characters WHERE id = %s AND guild_id = %s FOR UPDATE", (character_id, guild_id))
                row = await cursor.fetchone()
                if not row:
                    await db.rollback()
                    return False, "character_missing", None, None
                characters[character_id] = row
            if characters[sender_character_id][0] != sender_id or characters[recipient_character_id][0] != recipient_id:
                await db.rollback()
                return False, "character_owner", None, None
            if characters[sender_character_id][1] < amount:
                await db.rollback()
                return False, "insufficient", None, None
            sender_balance, recipient_balance = characters[sender_character_id][1] - amount, characters[recipient_character_id][1] + amount
            await cursor.execute("UPDATE rp_characters SET nax_balance = %s WHERE id = %s", (sender_balance, sender_character_id))
            await cursor.execute("UPDATE rp_characters SET nax_balance = %s WHERE id = %s", (recipient_balance, recipient_character_id))
            await _record_transfer(cursor, guild_id, "nax", sender_id, recipient_id, amount, reason, sender_character_id, recipient_character_id)
        await db.commit()
        return True, "ok", sender_balance, recipient_balance
    except Exception:
        await db.rollback()
        raise
