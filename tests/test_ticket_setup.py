"""Interactive panel setup, authorization, navigation and draft isolation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from discord.ext import commands
import pytest

from src.commands.support import ticket as command
from src.utils import ticket_setup as setup
from src.utils.tickets import PanelDraft, TicketError
from test_tickets import destination


def session(monkeypatch):
    env = destination()
    monkeypatch.setattr(setup, "GUILD_IDS", {1})
    env.interaction.user = env.admin
    env.interaction.response = SimpleNamespace(
        is_done=lambda: False,
        edit_message=AsyncMock(),
        send_message=AsyncMock(),
        defer=AsyncMock(),
        send_modal=AsyncMock(),
    )
    env.interaction.edit_original_response = AsyncMock()
    env.interaction.original_response = AsyncMock()
    env.interaction.data = {"values": []}
    manager = SimpleNamespace(
        panels=AsyncMock(return_value=[]),
        panel=AsyncMock(return_value=SimpleNamespace(jump_url="https://discord.com/channels/1/20/200")),
        delete_panel=AsyncMock(),
    )
    context = setup.SetupContext(manager, lambda: command.TicketPanel(manager), AsyncMock(), 8, 1)
    return env, context


def panel_record(panel_id=1, **changes):
    return {
        "id": panel_id,
        "name": f"Support {panel_id}",
        "title": "Besoin d’aide ?",
        "description": None,
        "staff_role_ids": (5,),
        "category_id": 30,
        "channel_id": 20,
        "transcript_channel_id": None,
        "version": 1,
        **changes,
    }


def test_panel_command_has_no_parameters_and_opens_private_setup():
    async def scenario():
        async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
            bot._connection.user = discord.ClientUser(
                state=bot._connection,
                data={
                    "id": "99",
                    "username": "Aurum",
                    "discriminator": "0",
                    "avatar": None,
                },
            )
            await command.register(bot)
            panel = bot.tree.get_command("ticket").get_command("panel")
            assert panel.parameters == []
            interaction = SimpleNamespace(
                client=bot,
                user=SimpleNamespace(id=8),
                guild_id=1,
                response=SimpleNamespace(send_message=AsyncMock()),
                original_response=AsyncMock(),
            )
            await panel.callback(panel.binding, interaction)
            sent = interaction.response.send_message.await_args.kwargs
            assert isinstance(sent["view"], setup.SetupHome)
            assert sent["ephemeral"]
            assert {item.label for item in sent["view"].children} == {"Créer un panneau", "Gérer les panneaux"}
            assert sent["embed"].footer.text == "Aurum" and sent["embed"].footer.icon_url

    asyncio.run(scenario())


def test_wizard_guides_all_five_steps_and_only_publishes_at_the_end(monkeypatch):
    async def scenario():
        env, context = session(monkeypatch)
        wizard = setup.PanelWizard(context)
        await wizard.render(env.interaction)
        assert "Étape 1/5" in env.interaction.response.edit_message.await_args.kwargs["embed"].title
        await wizard.edit_text(env.interaction)
        modal = env.interaction.response.send_modal.await_args.args[0]
        modal.name_input._value = "Aide RP"
        modal.title_input._value = "Un souci RP ?"
        modal.text_input._value = "Explique ta demande."
        await modal.on_submit(env.interaction)
        assert wizard.draft.name == "Aide RP"
        await wizard.advance(env.interaction)
        assert wizard.step == 1 and isinstance(wizard.children[0], discord.ui.RoleSelect)
        with pytest.raises(TicketError, match="rôle"):
            await wizard.advance(env.interaction)
        env.interaction.data = {"values": ["5"]}
        await wizard.select_roles(env.interaction)
        await wizard.advance(env.interaction)
        assert wizard.step == 2 and wizard.children[0].channel_types == [discord.ChannelType.category]
        env.interaction.data = {"values": ["30"]}
        await wizard.select_channel(env.interaction)
        await wizard.advance(env.interaction)
        assert wizard.step == 3
        await wizard.clear_transcripts(env.interaction)
        await wizard.back(env.interaction)
        assert wizard.step == 2 and wizard.draft.category_id == 30
        await wizard.advance(env.interaction)
        await wizard.advance(env.interaction)
        assert wizard.step == 4
        context.service.panel.assert_not_awaited()
        env.interaction.data = {"values": ["20"]}
        await wizard.select_channel(env.interaction)
        await wizard.advance(env.interaction)
        context.service.panel.assert_awaited_once()
        draft = context.service.panel.await_args.args[1]
        assert draft.staff_role_ids == (5,) and draft.category_id == 30 and draft.channel_id == 20
        assert draft.transcript_channel_id is None
        assert wizard.is_finished()

    asyncio.run(scenario())


def test_cancel_and_switch_discard_unsaved_edits_without_changing_the_source_panel(monkeypatch):
    async def scenario():
        env, context = session(monkeypatch)
        record = panel_record()
        manager = setup.PanelManager(context, [record, panel_record(2)])
        manager.selected_id = 1
        await manager.edit(env.interaction)
        wizard = env.interaction.response.edit_message.await_args.kwargs["view"]
        wizard.draft.name = "Unsaved name"
        wizard.draft.staff_role_ids = (9,)
        await wizard.cancel(env.interaction)
        context.service.panel.assert_not_awaited()
        assert record["name"] == "Support 1" and record["staff_role_ids"] == (5,)
        assert isinstance(env.interaction.response.edit_message.await_args.kwargs["view"], setup.SetupHome)

    asyncio.run(scenario())


def test_setup_and_open_modal_recheck_owner_guild_permissions_and_expiry(monkeypatch):
    async def scenario():
        env, context = session(monkeypatch)
        wizard = setup.PanelWizard(context)
        assert await wizard.interaction_check(env.interaction)
        env.interaction.user = env.staff
        assert not await wizard.interaction_check(env.interaction)
        env.interaction.user = env.admin
        env.admin.guild_permissions = discord.Permissions.none()
        assert not await wizard.interaction_check(env.interaction)
        env.admin.guild_permissions = discord.Permissions(manage_guild=True)
        env.interaction.guild_id = 999
        assert not await wizard.interaction_check(env.interaction)
        env.interaction.guild_id = 1
        modal = setup.PanelTextModal(wizard)
        wizard.generation += 1
        with pytest.raises(TicketError, match="plus à jour"):
            await modal.on_submit(env.interaction)
        wizard.stop()
        assert not await wizard.interaction_check(env.interaction)

    asyncio.run(scenario())


def test_manager_paginates_and_requires_confirmation_to_delete_only_selected_panel(monkeypatch):
    async def scenario():
        env, context = session(monkeypatch)
        records = [panel_record(index) for index in range(1, 28)]
        manager = setup.PanelManager(context, records)
        await manager.render(env.interaction)
        assert len(manager.children[0].options) == 25
        await manager.next(env.interaction)
        assert len(manager.children[0].options) == 2
        env.interaction.data = {"values": ["27"]}
        await manager.choose(env.interaction)
        await manager.ask_delete(env.interaction)
        context.service.delete_panel.assert_not_awaited()
        assert manager.confirm_delete
        await manager.abort_delete(env.interaction)
        context.service.delete_panel.assert_not_awaited()
        await manager.ask_delete(env.interaction)
        context.service.panels.return_value = records[:-1]
        await manager.delete(env.interaction)
        assert context.service.delete_panel.await_args.args[1:3] == (27, 1)
        assert len(manager.panels) == 26 and manager.selected_id is None

    asyncio.run(scenario())


def test_transcripts_step_is_optional_and_keeps_it_distinct_from_general_logs(monkeypatch):
    async def scenario():
        env, context = session(monkeypatch)
        wizard = setup.PanelWizard(context, PanelDraft(transcript_channel_id=10), step=3)
        await wizard.render(env.interaction)
        embed = env.interaction.response.edit_message.await_args.kwargs["embed"]
        assert "/setlogs" in embed.description
        await wizard.clear_transcripts(env.interaction)
        assert wizard.draft.transcript_channel_id is None
        assert wizard.children[0].min_values == 0
        env.interaction.data = {"values": ["20"]}
        env.panel.permissions_for.side_effect = None
        env.panel.permissions_for.return_value = discord.Permissions.all()
        with pytest.raises(TicketError, match="privé"):
            await wizard.select_channel(env.interaction)

    asyncio.run(scenario())
