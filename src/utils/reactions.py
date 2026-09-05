import os
import logging
import discord
from discord import Message
from src.utils.db import get_db_connection

# Internal keys → display names (deliberately vague)
EGGS = {
    "champion":      "Champion",
    "l_accord":      "L'Accord",
    "l_essentiel":   "L'Essentiel",
    "le_seigneur":   "Le Seigneur",
    "l_hibiscus":    "L'Hibiscus",
    "l_insomniaque": "L'Insomniaque",
}
logger = logging.getLogger(__name__)


async def _mark_found(user_id: int, key: str) -> None:
    try:
        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "INSERT IGNORE INTO discoveries (user_id, egg_key) VALUES (%s, %s)",
            (user_id, key)
        )
        await db.commit()
        await cursor.close()
        db.close()
    except Exception:
        logger.exception("Impossible d'enregistrer la découverte user=%s key=%s", user_id, key)


async def handle(message: Message) -> None:
    content = message.content.strip()
    low = content.lower()
    uid = message.author.id
    gid = message.guild.id if message.guild else 0

    if low == "gg":
        await message.add_reaction("🏆")
        await _mark_found(uid, "champion")

    if low == "ok":
        await message.add_reaction("👍")
        await _mark_found(uid, "l_accord")

    if len(content) == 1 and content.isascii() and content.strip():
        await message.add_reaction("🤏")
        await _mark_found(uid, "l_essentiel")

    if low == "un anneau":
        asset = os.path.join(os.path.dirname(__file__), "..", "assets", "one_bot.jpg")
        if os.path.exists(asset):
            await message.reply(file=discord.File(asset))
        await _mark_found(uid, "le_seigneur")
