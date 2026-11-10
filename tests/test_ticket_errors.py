"""Expected ticket failures must not trigger duplicate replies or technical alerts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from discord import app_commands
from discord.ext import commands
import pytest

from src.commands.support import ticket as ticket_command
from src.utils import command_errors, ticket_errors, ticket_service
from src.utils.tickets import TicketError
from test_tickets import destination, install_session, ticket


@pytest.mark.parametrize("kind", ["expected", "forbidden", "unexpected"])
def test_group_and_global_error_handlers_send_one_reply_and_report_only_unexpected_errors(monkeypatch, kind):
    async def scenario():
        env = destination()
        monkeypatch.setattr(ticket_command, "GUILD_IDS", {1})
        original = {
            "expected": TicketError("Ce membre est le créateur du ticket ; il n'a pas besoin d'être ajouté."),
            "forbidden": discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions"),
            "unexpected": RuntimeError("Unexpected storage failure"),
        }[kind]
        local_report = AsyncMock(return_value="local-ref")
        global_report = AsyncMock(return_value="global-ref")
        monkeypatch.setattr(ticket_errors, "report_error", local_report)
        monkeypatch.setattr(command_errors, "report_error", global_report)
        async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
            group = ticket_command.Tickets(SimpleNamespace(mutate=AsyncMock(side_effect=original)))
            bot.tree.add_command(group)
            add = group.get_command("add")
            interaction = env.interaction
            interaction.client, interaction.command, interaction.extras = bot, add, {}
            interaction.response = SimpleNamespace(defer=AsyncMock(), is_done=lambda: True, send_message=AsyncMock())
            interaction.followup = SimpleNamespace(send=AsyncMock())

            # Follow the same invocation/local-handler/tree-handler sequence as discord.py.
            with pytest.raises(app_commands.CommandInvokeError) as caught:
                await add._invoke_with_namespace(interaction, SimpleNamespace(user=env.creator))
            await add._invoke_error_handlers(interaction, caught.value)
            await command_errors.handle_app_command_error(bot, interaction, caught.value)
            assert interaction.extras[command_errors.ERROR_HANDLED_KEY]
            interaction.followup.send.assert_awaited_once()
            interaction.response.send_message.assert_not_awaited()
            global_report.assert_not_awaited()
            message = interaction.followup.send.await_args.args[0]
            assert interaction.followup.send.await_args.kwargs["ephemeral"]
            if kind == "unexpected":
                local_report.assert_awaited_once()
                assert local_report.await_args.kwargs["error"] is original
                assert local_report.await_args.kwargs["source"] == "/ticket add"
                assert "local-ref" in message
            else:
                local_report.assert_not_awaited()
                assert "Référence" not in message
                assert "créateur" in message if kind == "expected" else "permissions" in message

    asyncio.run(scenario())


def test_global_fallback_still_reports_unhandled_errors_with_the_full_command_name(monkeypatch):
    async def scenario():
        report = AsyncMock(return_value="technical-ref")
        monkeypatch.setattr(command_errors, "report_error", report)
        original = RuntimeError("Failure")
        command = SimpleNamespace(qualified_name="ticket add", name="add")
        error = app_commands.CommandInvokeError(command, original)
        interaction = SimpleNamespace(
            extras={},
            command=command,
            guild_id=1,
            user=SimpleNamespace(id=2),
            response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        bot = SimpleNamespace()
        await command_errors.handle_app_command_error(bot, interaction, error)
        await command_errors.handle_app_command_error(bot, interaction, error)
        report.assert_awaited_once()
        assert report.await_args.kwargs["error"] is original
        assert report.await_args.kwargs["source"] == "/ticket add"
        interaction.response.send_message.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "action,target,expected",
    [
        ("added", "creator", "créateur"),
        ("removed", "creator", "retirer le créateur"),
        ("added", "staff", "rôles"),
        ("removed", "staff", "personnel"),
    ],
)
def test_membership_refusals_identify_the_selected_target_and_do_not_change_permissions(
    monkeypatch, action, target, expected
):
    async def scenario():
        env = destination()
        env.interaction.user = env.admin
        session = SimpleNamespace(get=AsyncMock(return_value=ticket()), event=AsyncMock())
        install_session(monkeypatch, session)
        with pytest.raises(TicketError, match=expected):
            await ticket_service.TicketService().mutate(env.interaction, action, user=getattr(env, target))
        env.current.edit.assert_not_awaited()
        session.event.assert_not_awaited()

    asyncio.run(scenario())


def test_missing_actor_permission_is_distinct_from_automatic_target_access(monkeypatch):
    async def scenario():
        env = destination()
        env.interaction.user = env.creator
        install_session(monkeypatch, SimpleNamespace(get=AsyncMock(return_value=ticket())))
        with pytest.raises(TicketError, match="réservée au personnel autorisé"):
            await ticket_service.TicketService().mutate(env.interaction, "added", user=env.outsider)
        env.current.edit.assert_not_awaited()

    asyncio.run(scenario())
