"""Creator-only close controls, persistent routing and private confirmation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from discord.ext import commands
import pytest

from src.commands.support import ticket as command
from src.utils import ticket_controls as controls
from src.utils import ticket_service as service
from src.utils.tickets import TicketError
from test_tickets import destination, install_session, ticket


def interaction_env(monkeypatch):
    env = destination()
    monkeypatch.setattr(controls, "GUILD_IDS", {1})
    interaction = env.interaction
    interaction.response = SimpleNamespace(defer=AsyncMock(), edit_message=AsyncMock(), send_message=AsyncMock())
    interaction.followup = SimpleNamespace(send=AsyncMock())
    interaction.edit_original_response = AsyncMock()
    return env


@pytest.mark.parametrize("identity", ["creator", "staff", "admin", "outsider"])
def test_close_button_only_offers_a_confirmation_to_the_creator(monkeypatch, identity):
    async def scenario():
        env = interaction_env(monkeypatch)
        env.interaction.user = getattr(env, identity)
        install_session(monkeypatch, SimpleNamespace(get=AsyncMock(return_value=ticket())))
        view = controls.TicketCloseView(service.TicketService())
        if identity == "creator":
            await view.close.callback(env.interaction)
            kwargs = env.interaction.followup.send.await_args.kwargs
            assert kwargs["ephemeral"]
            assert kwargs["embed"].description == "Es-tu sûr de vouloir fermer ce ticket ?"
            assert kwargs["embed"].footer.text == "Aurum"
            assert kwargs["embed"].footer.icon_url == "https://example.test/avatar.png"
            confirmation = kwargs["view"]
            assert confirmation.confirm.label == "Fermer"
            assert confirmation.confirm.style == discord.ButtonStyle.danger
            assert confirmation.cancel.label == "Annuler"
            env.current.edit.assert_not_awaited()
        else:
            with pytest.raises(TicketError):
                await view.close.callback(env.interaction)
            env.interaction.followup.send.assert_not_awaited()
            env.current.edit.assert_not_awaited()

    asyncio.run(scenario())


def test_close_confirmation_is_single_use_and_uses_the_transcript_closure_path(monkeypatch):
    async def scenario():
        env = interaction_env(monkeypatch)
        manager = SimpleNamespace(
            mutate=AsyncMock(return_value=(ticket(status="closed"), b"history")),
            send_transcript=AsyncMock(return_value=None),
        )
        view = controls.TicketCloseConfirmation(manager, 2, 1, 10, 1)
        await view.confirm.callback(env.interaction)
        await view.confirm.callback(env.interaction)
        manager.mutate.assert_awaited_once_with(
            env.interaction,
            "closed",
            reason="Fermeture demandée par le créateur via le bouton.",
            creator_only=True,
            expected_ticket_id=1,
        )
        manager.send_transcript.assert_awaited_once()
        assert view.is_finished()
        assert "sauvegardé" in env.interaction.edit_original_response.await_args.kwargs["content"]

    asyncio.run(scenario())


@pytest.mark.parametrize("blocked", ["staff", "admin", "other_channel", "other_guild", "expired", "cancelled"])
def test_confirmation_cannot_close_for_staff_or_after_cancellation_or_expiry(monkeypatch, blocked):
    async def scenario():
        env = interaction_env(monkeypatch)
        manager = SimpleNamespace(mutate=AsyncMock(), send_transcript=AsyncMock())
        view = controls.TicketCloseConfirmation(manager, 2, 1, 10, 1)
        if blocked in {"staff", "admin"}:
            env.interaction.user = getattr(env, blocked)
        elif blocked == "other_channel":
            env.interaction.channel_id = 20
        elif blocked == "other_guild":
            env.interaction.guild_id = 999
        elif blocked == "expired":
            view.stop()
        else:
            await view.cancel.callback(env.interaction)
        await view.confirm.callback(env.interaction)
        manager.mutate.assert_not_awaited()
        manager.send_transcript.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize("blocked", ["staff", "admin", "closed", "different_ticket"])
def test_creator_and_ticket_identity_are_rechecked_inside_the_closing_transaction(monkeypatch, blocked):
    async def scenario():
        env = interaction_env(monkeypatch)
        current = ticket(status="closed" if blocked == "closed" else "open")
        install_session(monkeypatch, SimpleNamespace(get=AsyncMock(return_value=current)))
        if blocked in {"staff", "admin"}:
            env.interaction.user = getattr(env, blocked)
        with pytest.raises(TicketError):
            await service.TicketService().mutate(
                env.interaction,
                "closed",
                reason="Fermeture par bouton",
                creator_only=True,
                expected_ticket_id=99 if blocked == "different_ticket" else 1,
            )
        env.current.edit.assert_not_awaited()

    asyncio.run(scenario())


def test_close_button_is_registered_as_persistent_after_a_restart():
    async def scenario():
        async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
            await command.register(bot)
            close_view = next(view for view in bot.persistent_views if isinstance(view, controls.TicketCloseView))
            assert close_view.is_persistent()
            assert close_view.close.custom_id == "aurum:tickets:close:v1"

    asyncio.run(scenario())
