import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from discord.ext import commands

from src.commands.economie import help as help_command
from src.commands.rp import roll as roll_command


def test_public_dice_menu_matches_roll_help_and_replaces_roleplay_entry():
    async def scenario():
        async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
            bot._connection.user = discord.ClientUser(state=bot._connection, data={
                "id": "99", "username": "MinamixBot", "discriminator": "0", "avatar": None,
            })
            await help_command.register(bot)
            await roll_command.register(bot)
            interaction = SimpleNamespace(
                client=bot,
                user=SimpleNamespace(id=42, guild_permissions=discord.Permissions.none()),
                permissions=discord.Permissions.none(),
                response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()),
                original_response=AsyncMock(),
            )
            await bot.tree.get_command("help").callback(interaction)
            kwargs = interaction.response.send_message.await_args.kwargs
            assert kwargs["ephemeral"]
            view = kwargs["view"]
            select = next(item for item in view.children if isinstance(item, discord.ui.Select))
            options = {option.value: option.label for option in select.options}
            assert options["dice"] == "Dés"
            assert "rp" in options
            select._values = ["rp"]
            await select.callback(interaction)
            roleplay = interaction.response.edit_message.await_args.kwargs["embed"]
            assert "/roll" not in roleplay.description
            assert "/rplist" in roleplay.description
            select._values = ["dice"]
            await select.callback(interaction)
            dice_page = interaction.response.edit_message.await_args.kwargs["embed"]
            assert interaction.response.edit_message.await_args.kwargs["view"] is view
            await bot.tree.get_command("roll").callback(interaction, "help")
            direct_page = interaction.response.send_message.await_args.kwargs["embed"]
            assert dice_page.to_dict() == direct_page.to_dict()
            assert "2 4df" in dice_page.description
    asyncio.run(scenario())
