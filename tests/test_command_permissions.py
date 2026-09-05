import asyncio

import discord
from discord.ext import commands

from src.core.loader import load_modules
from src.utils.permissions import ADMIN_COMMANDS, RP_MANAGER_COMMANDS


def test_registered_command_permissions():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    asyncio.run(load_modules(bot, "src/commands", "CMD"))
    registered = {command.name: command for command in bot.tree.get_commands()}

    assert len(registered) == 51
    assert not (ADMIN_COMMANDS | RP_MANAGER_COMMANDS) - registered.keys()

    for name in ADMIN_COMMANDS:
        command = registered[name]
        assert command.default_permissions is not None
        assert command.default_permissions.manage_guild
        assert command.checks

    for name in RP_MANAGER_COMMANDS:
        assert registered[name].checks
