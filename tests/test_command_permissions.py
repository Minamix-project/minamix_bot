import asyncio

import discord
from discord.ext import commands

from src.core.loader import load_modules
from src.utils.permissions import ADMIN_COMMANDS


def test_registered_command_permissions():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    asyncio.run(load_modules(bot, "src/commands", "CMD"))
    registered = {command.name: command for command in bot.tree.get_commands()}

    assert len(registered) == 61
    assert "reminder" in registered
    assert "rappel" not in registered
    assert "remind" not in registered
    assert not isinstance(registered["reminder"], discord.app_commands.Group)
    assert registered["reminder"].parameters == []
    assert registered["reminder"].to_dict(bot.tree)["dm_permission"] is False
    for name in ("rproles", "rpprofile"):
        command = registered[name]
        assert command.parameters == []
        assert command.default_permissions is None
        assert command.to_dict(bot.tree)["dm_permission"] is False
    history = registered["messagehistory"]
    assert history.default_permissions.manage_guild
    assert not history.default_permissions.manage_messages
    assert history.to_dict(bot.tree)["default_member_permissions"] == discord.Permissions(manage_guild=True).value
    assert {command.name for command in history.commands} == {"recent", "view", "status", "configure", "purge", "import"}
    for name in ("configure", "purge", "import"):
        assert history.get_command(name).checks
    assert not ADMIN_COMMANDS - registered.keys()

    for name in ADMIN_COMMANDS:
        command = registered[name]
        assert command.default_permissions is not None
        assert command.default_permissions.manage_guild
        assert command.to_dict(bot.tree)["default_member_permissions"] == discord.Permissions(manage_guild=True).value
        assert command.checks
