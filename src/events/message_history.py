"""Capture live messages and maintain bounded persistent history."""

import asyncio
import logging

from discord.ext import commands, tasks

from src.config import GUILD_IDS
from src.utils.message_history import initialize_history_store
from src.utils.message_logs import MessageSnapshot

logger = logging.getLogger(__name__)


class MessageHistory(commands.Cog):
    def __init__(self, bot, store):
        self.bot = bot
        self.store = store
        self.importing_guilds: set[int] = set()
        self.maintain.start()

    async def cog_unload(self):
        task = self.maintain.get_task()
        self.maintain.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    @commands.Cog.listener("on_message")
    async def capture(self, message):
        if message.guild is None or message.guild.id not in GUILD_IDS:
            return
        if self.bot.user is not None and message.author.id == self.bot.user.id:
            return
        try:
            await self.store.record(
                message.guild.id, message.channel.id, message.id, "created", MessageSnapshot.from_message(message),
            )
        except Exception as exc:
            # Driver errors can contain SQL parameters; never log their bodies.
            logger.error("Message history capture failed guild=%s type=%s", message.guild.id, type(exc).__name__)

    @tasks.loop(minutes=15)
    async def maintain(self):
        try:
            guild_ids = await self.store.known_guilds()
        except Exception as exc:
            logger.error("Could not list history guilds type=%s", type(exc).__name__)
            return
        for guild_id in guild_ids:
            try:
                await self.store.cleanup(guild_id, active=guild_id in GUILD_IDS and self.bot.get_guild(guild_id) is not None)
            except Exception as exc:
                logger.error("Message history cleanup failed guild=%s type=%s", guild_id, type(exc).__name__)

    @maintain.before_loop
    async def before_maintain(self):
        await self.bot.wait_until_ready()


async def register(bot):
    await bot.add_cog(MessageHistory(bot, await initialize_history_store()))
