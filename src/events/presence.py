"""Rotate the bot's French Discord activities without duplicate background tasks."""

import asyncio
import logging
import os

import discord
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)
ROTATION_MINUTES = 5


def activities(bot_name):
    version = os.getenv("BOT_VERSION", "").strip()
    if version in {"", "dev", "unknown"}:
        version = "de développement"
    return (
        discord.Activity(type=discord.ActivityType.watching, name="Les bots prendre le pouvoir"),
        discord.Activity(type=discord.ActivityType.listening, name="Les plaintes des utilisateurs"),
        discord.Game(name=f"La version {version} de {bot_name}"[:128]),
        discord.Activity(type=discord.ActivityType.competing, name="La lutte pour l'égalité entre bots et humains"),
    )


class RotatingPresence(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.index = 0

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.rotate.is_running():
            self.rotate.start()

    @tasks.loop(minutes=ROTATION_MINUTES)
    async def rotate(self):
        if not self.bot.is_ready() or self.bot.user is None:
            return
        choices = activities(self.bot.user.name)
        try:
            await self.bot.change_presence(activity=choices[self.index])
        except (discord.ConnectionClosed, discord.HTTPException, OSError) as error:
            logger.warning("Could not update rotating presence type=%s", type(error).__name__)
            return
        self.index = (self.index + 1) % len(choices)

    async def cog_unload(self):
        task = self.rotate.get_task()
        self.rotate.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)


async def register(bot):
    await bot.add_cog(RotatingPresence(bot))
