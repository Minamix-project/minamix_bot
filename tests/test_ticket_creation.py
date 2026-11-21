"""Direct ticket creation preserves panel configuration, ownership and category limits."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from src.commands.support import ticket as command
from src.utils import ticket_service as service
from src.utils.tickets import CATEGORIES, TicketError
from test_ticket_setup import panel_record
from test_tickets import destination, install_session, ticket


def creation_session(monkeypatch, env, panels=None):
    panels = panels if panels is not None else [panel_record()]
    current = None

    async def create(channel_id, creator_id, category, panel, *, number, staff_role_ids, category_version, channel_base_name, admin_role_ids=()):
        nonlocal current
        current = ticket(
            channel_id=channel_id, creator_id=creator_id, category=category, ticket_number=number,
            panel_id=panel["id"], logs_channel_id=panel["logs_channel_id"],
            staff_role_ids=staff_role_ids, category_version=category_version, channel_base_name=channel_base_name,
        )

    session = SimpleNamespace(
        panels=AsyncMock(return_value=panels), panel_for_message=AsyncMock(return_value=panels[0] if panels else None),
        active=AsyncMock(return_value=None), next_number=AsyncMock(return_value=12),
        create=AsyncMock(side_effect=create), get=AsyncMock(side_effect=lambda channel_id: current), event=AsyncMock(),
    )
    install_session(monkeypatch, session)
    return session


@pytest.mark.parametrize("direct,on_behalf", [(False, False), (True, False), (True, True)])
def test_creation_paths_share_numbering_welcome_ownership_and_audit(monkeypatch, direct, on_behalf):
    async def scenario():
        env = destination()
        if on_behalf:
            env.interaction.user = env.admin
        if direct:
            env.interaction.message = None
        session = creation_session(monkeypatch, env)
        created = await service.TicketService().create(
            env.interaction, "bot", direct=direct, user=env.creator if on_behalf else None,
        )
        assert created.creator_id == env.creator.id and created.category == "bot"
        assert env.channels[40].name == "ticket-0012-🔴"
        session.active.assert_awaited_once_with(env.creator.id, "bot")
        session.event.assert_awaited_once_with(
            created, env.interaction.user.id, "created", CATEGORIES["bot"], staff=on_behalf,
        )
        welcome = env.channels[40].send.await_args
        assert welcome.args == ("Bienvenue <@2> !",)
        assert welcome.kwargs["allowed_mentions"].to_dict()["users"] == [env.creator.id]
        assert welcome.kwargs["embed"].footer.text == "Aurum"
        assert welcome.kwargs["embed"].title.startswith("🤖 Ticket #0012")
        assert "Précise la commande utilisée" in welcome.kwargs["embed"].description
        assert welcome.kwargs["view"].is_persistent()
        assert env.channels[40].overwrites[env.creator].view_channel
    asyncio.run(scenario())


@pytest.mark.parametrize("identity", ["creator", "staff"])
def test_non_admins_cannot_use_the_user_option_even_for_themselves(monkeypatch, identity):
    async def scenario():
        env = destination()
        env.interaction.user = getattr(env, identity)
        session = creation_session(monkeypatch, env)
        with pytest.raises(TicketError, match="administration"):
            await service.TicketService().create(env.interaction, "report", direct=True, user=env.interaction.user)
        session.panels.assert_not_awaited()
        env.guild.create_text_channel.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["bot", "foreign"])
def test_admin_creation_rejects_bots_and_foreign_members(monkeypatch, invalid):
    async def scenario():
        env = destination()
        env.interaction.user = env.admin
        target = env.outsider
        if invalid == "bot":
            target.bot = True
        else:
            target.guild = SimpleNamespace(id=999)
        creation_session(monkeypatch, env)
        with pytest.raises(TicketError, match="membre de ce serveur"):
            await service.TicketService().create(env.interaction, "report", direct=True, user=target)
        env.guild.create_text_channel.assert_not_awaited()
    asyncio.run(scenario())


def test_direct_creation_uses_the_current_channels_panel_when_several_exist(monkeypatch):
    async def scenario():
        env = destination()
        session = creation_session(monkeypatch, env, [panel_record(), panel_record(2, channel_id=10)])
        created = await service.TicketService().create(env.interaction, "character_validation", direct=True)
        assert created.panel_id == 2
        session.panel_for_message.assert_not_awaited()
    asyncio.run(scenario())


def test_ambiguous_panels_require_a_choice_and_explicit_choice_is_respected(monkeypatch):
    async def scenario():
        env = destination()
        creation_session(monkeypatch, env, [panel_record(), panel_record(2)])
        manager = service.TicketService()
        with pytest.raises(TicketError, match="Plusieurs panneaux"):
            await manager.create(env.interaction, "character_validation", direct=True)
        env.guild.create_text_channel.assert_not_awaited()
        created = await manager.create(env.interaction, "character_validation", direct=True, panel_id=2)
        assert created.panel_id == 2
    asyncio.run(scenario())


@pytest.mark.parametrize("hidden", [False, True])
def test_absent_or_hidden_panels_are_not_available_for_direct_creation(monkeypatch, hidden):
    async def scenario():
        env = destination()
        if hidden:
            env.interaction.user = env.outsider
        session = creation_session(monkeypatch, env, [panel_record()] if hidden else [])
        manager = service.TicketService()
        assert await manager.creation_panels(env.interaction) == []
        with pytest.raises(TicketError, match="Aucun panneau"):
            await manager.create(env.interaction, "character_validation", direct=True)
        with pytest.raises(TicketError, match="plus disponible"):
            await manager.create(env.interaction, "character_validation", direct=True, panel_id=1)
        session.active.assert_not_awaited()
        env.guild.create_text_channel.assert_not_awaited()
    asyncio.run(scenario())


def test_creation_for_another_member_uses_that_members_category_limit(monkeypatch):
    async def scenario():
        env = destination()
        env.interaction.user = env.admin
        session = creation_session(monkeypatch, env)
        session.active.return_value = ticket(category="bot")
        with pytest.raises(TicketError, match="Ce membre a déjà.*catégorie"):
            await service.TicketService().create(env.interaction, "bot", direct=True, user=env.creator)
        session.active.assert_awaited_once_with(env.creator.id, "bot")
        env.guild.create_text_channel.assert_not_awaited()
    asyncio.run(scenario())


def test_create_command_has_french_reason_choices_and_private_response():
    async def scenario():
        env = destination()
        env.interaction.user = env.admin
        env.interaction.response = SimpleNamespace(defer=AsyncMock())
        env.interaction.followup = SimpleNamespace(send=AsyncMock())
        manager = SimpleNamespace(create=AsyncMock(return_value=ticket()), creation_panels=AsyncMock(return_value=[]))
        group = command.Tickets(manager)
        create = group.get_command("create")
        options = {parameter.name: parameter for parameter in create.parameters}
        assert options["reason"].required
        assert options["reason"].autocomplete
        assert not options["reason"].choices
        assert not options["user"].required and not options["panel"].required
        await create.callback(group, env.interaction, "report", user=env.creator, panel="1")
        manager.create.assert_awaited_once_with(env.interaction, "report", direct=True, user=env.creator, panel_id=1)
        env.interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        assert env.interaction.followup.send.await_args.kwargs["ephemeral"]
        assert env.interaction.followup.send.await_args.kwargs["allowed_mentions"].to_dict()["parse"] == []
        manager.create.reset_mock()
        with pytest.raises(TicketError, match="Choisis un panneau"):
            await create.callback(group, env.interaction, "report", panel="invalid")
        manager.create.assert_not_awaited()
    asyncio.run(scenario())


def test_panel_autocomplete_filters_names_and_limits_results_to_discord_capacity(monkeypatch):
    async def scenario():
        env = destination()
        monkeypatch.setattr(command, "GUILD_IDS", {1})
        manager = SimpleNamespace(creation_panels=AsyncMock(return_value=[panel_record(index) for index in range(1, 40)]))
        group = command.Tickets(manager)
        choices = await group.create_panel_choices(env.interaction, "Support")
        assert len(choices) == 25
        choices = await group.create_panel_choices(env.interaction, "39")
        assert [choice.value for choice in choices] == ["39"]
        manager.creation_panels.side_effect = TicketError("Une opération sur les tickets est en cours.")
        assert await group.create_panel_choices(env.interaction, "Support") == []
        env.interaction.guild_id = 999
        assert await group.create_panel_choices(env.interaction, "Support") == []
    asyncio.run(scenario())


def test_reopening_checks_only_the_closed_tickets_category(monkeypatch):
    async def scenario():
        env = destination()
        env.interaction.user = env.staff
        closed = replace(ticket(), status="closed", saved_overwrites="[]")
        session = SimpleNamespace(
            get=AsyncMock(return_value=closed), active=AsyncMock(return_value=None), reopen=AsyncMock(), event=AsyncMock(),
        )
        install_session(monkeypatch, session)
        await service.TicketService().mutate(env.interaction, "reopened")
        session.active.assert_awaited_once_with(closed.creator_id, closed.category)
        session.reopen.assert_awaited_once_with(closed)
    asyncio.run(scenario())
