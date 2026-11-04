import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from discord.ext import commands
import pytest

from src.commands.economie import help as help_command
from src.commands.economie import pay as pay_command


@asynccontextmanager
async def help_session(permissions):
    async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
        bot._connection.user = discord.ClientUser(state=bot._connection, data={
            "id": "99", "username": "MinamixBot", "discriminator": "0", "avatar": None,
        })
        await help_command.register(bot)
        await pay_command.register(bot)
        interaction = SimpleNamespace(
            client=bot, user=SimpleNamespace(id=42, guild_permissions=permissions), permissions=permissions,
            response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()),
            original_response=AsyncMock(),
        )
        await bot.tree.get_command("help").callback(interaction)
        view = interaction.response.send_message.await_args.kwargs["view"]
        select = next(item for item in view.children if isinstance(item, discord.ui.Select))
        yield bot, interaction, select


@pytest.mark.parametrize("permissions,visible,management", [
    (discord.Permissions.none(), False, False),
    (discord.Permissions(manage_messages=True), False, False),
    (discord.Permissions(manage_guild=True), True, True),
    (discord.Permissions(administrator=True), True, True),
])
def test_history_help_uses_admin_convention_and_respects_access(permissions, visible, management):
    async def scenario():
        async with help_session(permissions) as (_bot, interaction, select):
            options = {option.value: option.label for option in select.options}
            for category in help_command.ADMIN_HELP_CATEGORIES:
                assert (category in options) is visible
            assert ("message_history" in options) is visible
            if not visible:
                return
            assert options["message_history"] == "Admin · Suivi des messages"
            select._values = ["message_history"]
            await select.callback(interaction)
            embed = interaction.response.edit_message.await_args.kwargs["embed"]
            assert embed.title == "📋 Administration · Suivi des messages"
            for name in ("recent", "view", "status"):
                assert f"/messagehistory {name}" in embed.description
            for name in ("import", "configure", "purge"):
                assert (f"/messagehistory {name}" in embed.description) is management
            assert "Gérer le serveur" in embed.description
            assert len(embed.description) <= 4096
    asyncio.run(scenario())


@pytest.mark.parametrize("category", sorted(help_command.ADMIN_HELP_CATEGORIES))
def test_admin_help_rechecks_access_after_permission_loss(category):
    async def scenario():
        async with help_session(discord.Permissions(manage_guild=True)) as (_bot, interaction, select):
            interaction.user.guild_permissions = discord.Permissions(manage_messages=True)
            interaction.permissions = discord.Permissions(manage_messages=True)
            select._values = [category]
            await select.callback(interaction)
            interaction.response.edit_message.assert_not_awaited()
            kwargs = interaction.response.send_message.await_args.kwargs
            assert kwargs["ephemeral"]
            assert "Gérer le serveur" in interaction.response.send_message.await_args.args[0]
    asyncio.run(scenario())


def test_transfers_are_documented_in_economy_and_roleplay_with_real_options():
    async def scenario():
        async with help_session(discord.Permissions.none()) as (bot, interaction, select):
            pay = bot.tree.get_command("pay")
            assert [parameter.name for parameter in pay.parameters] == ["user", "amount", "reason"]
            assert all(parameter.required for parameter in pay.parameters)
            for category in ("economy", "rp"):
                select._values = [category]
                await select.callback(interaction)
                embed = interaction.response.edit_message.await_args.kwargs["embed"]
                assert "/pay <user> <amount> <reason>" in embed.description
                assert "NAX" in embed.description
                if category == "economy":
                    assert "coins" in embed.description
                else:
                    assert "personnages RP" in embed.description
    asyncio.run(scenario())


def test_history_management_is_grouped_in_history_help_instead_of_configuration():
    async def scenario():
        async with help_session(discord.Permissions(manage_guild=True)) as (_bot, interaction, select):
            select._values = ["system"]
            await select.callback(interaction)
            description = interaction.response.edit_message.await_args.kwargs["embed"].description
            assert "/setlogs" in description
            assert "/messagehistory" not in description
            select._values = ["admin_economy"]
            await select.callback(interaction)
            description = interaction.response.edit_message.await_args.kwargs["embed"].description
            assert "/economyconfig" in description
            assert "transferts" in description
    asyncio.run(scenario())
