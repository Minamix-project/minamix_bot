import discord
import logging
from discord import Message
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.config import GUILD_IDS

logger = logging.getLogger(__name__)


async def register(bot):
    @bot.listen("on_message")
    async def on_message_antispam(message: Message):
        if message.author.bot:
            return
        if message.guild is None or message.guild.id not in GUILD_IDS:
            return

        db = await get_db_connection()
        try:
            async with db.cursor() as cursor:
                await cursor.execute(
                    "SELECT 1 FROM antispam_channels WHERE guild_id = %s AND channel_id = %s",
                    (message.guild.id, message.channel.id),
                )
                is_antispam = (await cursor.fetchone()) is not None
                if not is_antispam:
                    return
                await cursor.execute(
                    "SELECT value FROM guild_config WHERE guild_id = %s AND config_key = 'logs_channel'",
                    (message.guild.id,),
                )
                logs_result = await cursor.fetchone()
        finally:
            db.close()

        deleted = False
        try:
            await message.delete()
            deleted = True
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("Suppression anti-spam refusée guild=%s message=%s: %s", message.guild.id, message.id, exc)

        banned = False
        try:
            await message.guild.ban(
                message.author,
                reason="Message posté dans un channel anti-spam",
                delete_message_days=0
            )
            banned = True
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.error("Ban anti-spam refusé guild=%s user=%s: %s", message.guild.id, message.author.id, exc)

        if not logs_result:
            return

        logs_channel = message.guild.get_channel(int(logs_result[0]))
        if not logs_channel:
            return

        embed = discord.Embed(
            title="🔨 Ban automatique — Anti-spam" if banned else "🚨 Échec du ban automatique",
            color=discord.Color.red() if banned else discord.Color.orange(),
        )
        embed.add_field(name="Utilisateur", value=f"{message.author} (`{message.author.id}`)", inline=False)
        embed.add_field(name="Channel", value=f"<#{message.channel.id}>", inline=False)
        embed.add_field(name="Message", value=message.content[:500] if message.content else "*vide*", inline=False)
        embed.add_field(name="Résultat", value=f"Message supprimé : {'oui' if deleted else 'non'}\nUtilisateur banni : {'oui' if banned else 'non'}", inline=False)
        embed.timestamp = message.created_at

        try:
            await logs_channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.error("Envoi du log anti-spam refusé guild=%s: %s", message.guild.id, exc)
