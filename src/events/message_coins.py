import time
import random
import discord
from discord import Message
from src.utils.wallet import modify_user_balance
from src.utils.reactions import handle as _react
from src.config import GUILD_IDS

_last_gain: dict[int, float] = {}
_last_seen_update: dict[int, float] = {}
COOLDOWN = 60
SEEN_DEBOUNCE = 300


async def register(bot):
    @bot.listen("on_message")
    async def on_message_coins(message: Message):
        if message.author.bot:
            return

        if message.guild is None or message.guild.id not in GUILD_IDS:
            return

        if bot.user in message.mentions:
            from datetime import datetime
            from src.utils.reactions import _mark_found
            now_time = datetime.now().time()
            if 1 <= now_time.hour < 5:
                await _mark_found(message.author.id, "l_insomniaque")
                await message.reply("T'as vraiment que ça à faire à cette heure-ci ?")
            else:
                await message.reply("Tu veux quoi toi ?")
            return

        await _react(message)

        now = time.time()

        # Update last_seen (debounced every 5 min)
        if now - _last_seen_update.get(message.author.id, 0) >= SEEN_DEBOUNCE:
            _last_seen_update[message.author.id] = now
            try:
                from src.utils.db import get_db_connection
                db = await get_db_connection()
                cursor = await db.cursor()
                await cursor.execute(
                    "INSERT INTO users (user_id, last_seen) VALUES (%s, NOW()) "
                    "ON DUPLICATE KEY UPDATE last_seen = NOW()",
                    (message.author.id,)
                )
                await db.commit()
                await cursor.close()
                db.close()
            except Exception:
                pass

        if now - _last_gain.get(message.author.id, 0) < COOLDOWN:
            await bot.process_commands(message)
            return
        _last_gain[message.author.id] = now

        gain = random.randint(30, 50) if len(message.content) >= 1000 else random.randint(15, 25)

        try:
            from src.utils.db import get_db_connection
            db = await get_db_connection()
            await modify_user_balance(db, message.guild.id, message.author.id, gain, "add")
            db.close()
        except Exception:
            pass

        await bot.process_commands(message)
