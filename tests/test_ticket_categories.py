"""Configurable category defaults, private editing and live ticket presentation."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from src.commands.support import ticket as command
from src.utils import ticket_categories as editor
from src.utils import ticket_service as service
from src.utils import tickets as store
from src.utils.tickets import CATEGORY_OPTIONS, CategoryDraft, TicketError
from test_ticket_creation import creation_session
from test_ticket_role_sync import synchronization
from test_ticket_setup import session as setup_session
from test_tickets import category_record, destination


def test_category_editor_keeps_roles_optional_and_drafts_private_until_save(monkeypatch):
    async def scenario():
        env, context = setup_session(monkeypatch)
        records = [category_record(key) for key in CATEGORY_OPTIONS]
        context.service.save_category = AsyncMock()
        context.service.categories = AsyncMock(return_value=records)
        view = editor.CategoryEditor(context, records)
        await view.render(env.interaction)
        env.interaction.data = {"values": ["report"]}
        await view.choose(env.interaction)
        assert view.children[1].min_values == 0
        await view.edit(env.interaction)
        modal = env.interaction.response.send_modal.await_args.args[0]
        modal.name_input._value = "Médiation"
        modal.emoji_input._value = "⚖️"
        modal.description_input._value = "Une situation à régler avec le staff"
        modal.welcome_input._value = "Décris la situation et les personnes concernées."
        await modal.on_submit(env.interaction)
        assert view.draft.name == "Médiation" and view.draft.category_key == "report"
        assert records[2]["name"] == "Plaintes"
        env.interaction.data = {"values": ["5"]}
        await view.select_roles(env.interaction)
        assert view.draft.staff_role_ids == (5,)
        env.interaction.data = {"values": []}
        await view.select_roles(env.interaction)
        assert view.draft.staff_role_ids == ()
        context.service.save_category.assert_not_awaited()
        await view.save(env.interaction)
        draft = context.service.save_category.await_args.args[1]
        assert draft.name == "Médiation" and draft.staff_role_ids == ()
        assert view.draft is None and "enregistrée" in view.notice
    asyncio.run(scenario())


def test_category_editor_rechecks_admin_and_rejects_stale_modals(monkeypatch):
    async def scenario():
        env, context = setup_session(monkeypatch)
        view = editor.CategoryEditor(context, [category_record(), category_record("bot")])
        env.interaction.data = {"values": ["report"]}
        await view.choose(env.interaction)
        modal = editor.CategoryTextModal(view)
        env.interaction.data = {"values": ["bot"]}
        await view.choose(env.interaction)
        with pytest.raises(TicketError, match="plus à jour"):
            await modal.on_submit(env.interaction)
        env.interaction.user.guild_permissions = discord.Permissions.none()
        assert not await view.interaction_check(env.interaction)
        assert view.draft.category_key == "bot"
    asyncio.run(scenario())


def test_category_rename_refreshes_opening_messages_topics_and_every_panel(monkeypatch):
    async def scenario():
        env, _role, current, draft, session, welcome = synchronization(monkeypatch)
        current.panel_id = None
        draft.name, draft.emoji = "Médiation", "⚖️"
        draft.description, draft.welcome = "Contacte la médiation", "Explique la situation au staff."
        old = category_record()
        updated = {**old, "name": draft.name, "emoji": draft.emoji,
                   "description": draft.description, "welcome": draft.welcome, "staff_role_ids": (6,), "version": 2}
        session.categories.side_effect = [[old], [updated]]
        session.panels.return_value = [{"id": 1, "channel_id": 20, "message_id": 201},
                                      {"id": 2, "channel_id": 20, "message_id": 202}]
        messages = [SimpleNamespace(author=env.guild.me, edit=AsyncMock()) for _ in range(2)]
        env.panel.fetch_message = AsyncMock(side_effect=messages)
        await service.TicketService().save_category(env.interaction, draft, lambda: command.TicketPanel(None))
        embed = welcome.edit.await_args.kwargs["embed"]
        assert embed.title == "⚖️ Ticket #0001 — Médiation"
        assert draft.welcome in embed.description and embed.footer.text == "Aurum"
        assert welcome.edit.await_args.kwargs["allowed_mentions"].to_dict()["parse"] == []
        assert env.current.edit.await_args.kwargs["topic"] == "Aurum | Médiation | 2"
        for message in messages:
            options = message.edit.await_args.kwargs["view"].children[0].options
            assert options[0].label == "Médiation" and str(options[0].emoji) == "⚖️"
            assert options[0].value == current.category == "report"
        assert session.update_category.await_args.args[1]["version"] == 2
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["version", "emoji", "permission"])
def test_invalid_category_updates_do_not_mutate_tickets(monkeypatch, failure):
    async def scenario():
        env, _role, _current, draft, session, message = synchronization(monkeypatch)
        if failure == "version":
            draft.version = 0
        elif failure == "emoji":
            draft.emoji = "invalid"
        else:
            env.interaction.user = env.creator
        with pytest.raises(TicketError):
            await service.TicketService().save_category(env.interaction, draft, lambda: command.TicketPanel(None))
        session.save_category.assert_not_awaited()
        env.current.edit.assert_not_awaited()
        message.edit.assert_not_awaited()
    asyncio.run(scenario())


def test_creation_uses_category_roles_and_allows_unconfigured_defaults(monkeypatch):
    async def scenario():
        env = destination()
        session = creation_session(monkeypatch, env)
        session.category.side_effect = None
        session.category.return_value = category_record("bot")
        created = await service.TicketService().create(env.interaction, "bot", direct=True)
        assert created.staff_role_ids == ()
        assert env.staff_role not in env.channels[40].overwrites
        assert env.channels[40].overwrites[env.creator].view_channel
        session.set_welcome_message.assert_awaited_once_with(created, 4000)
    asyncio.run(scenario())


def test_reason_autocomplete_uses_current_guild_category_names(monkeypatch):
    async def scenario():
        env = destination()
        monkeypatch.setattr(command, "GUILD_IDS", {1})
        manager = SimpleNamespace(categories=AsyncMock(return_value=[category_record(name="Médiation", emoji="⚖️")]))
        group = command.Tickets(manager)
        choices = await group.create_reason_choices(env.interaction, "médi")
        assert [(choice.name, choice.value) for choice in choices] == [("⚖️ Médiation", "report")]
        assert await group.create_reason_choices(env.interaction, "unknown") == []
    asyncio.run(scenario())


def test_mysql_defaults_are_empty_persistent_and_guild_scoped_and_renaming_keeps_limits(monkeypatch):
    import aiomysql
    from src.core.db_init import init_db

    port = os.getenv("TICKET_TEST_DB_PORT") or os.getenv("REMINDER_TEST_DB_PORT")
    if not port:
        pytest.skip("Requires a disposable MySQL test database")

    async def connect():
        return await aiomysql.connect(
            host="127.0.0.1", port=int(port), user="root", password="", db="reminder_test",
            autocommit=True, charset="utf8mb4",
        )

    monkeypatch.setattr(store, "get_db_connection", connect)

    async def scenario():
        db = await connect()
        try:
            await init_db(db)
            async with db.cursor() as cursor:
                await cursor.execute("DELETE FROM tickets")
                await cursor.execute("DELETE FROM ticket_categories")
        finally:
            db.close()
        async with store.ticket_session(1) as session:
            categories = await session.categories()
            assert [category["name"] for category in categories] == [option.label for option in CATEGORY_OPTIONS.values()]
            assert all(category["staff_role_ids"] == () for category in categories)
            draft = CategoryDraft.from_category(await session.category("report"))
            draft.name, draft.emoji, draft.staff_role_ids = "Médiation", "⚖️", (5,)
            await session.save_category(draft)
            category = await session.category("report")
            await session.create(100, 2, "report", {"transcript_channel_id": None}, staff_role_ids=(5,), category_version=2)
            created = await session.get(100)
            await session.set_welcome_message(created, 12345)
            assert category["version"] == 2 and created.label == "Médiation"
        async with store.ticket_session(1) as session:
            category = await session.category("report")
            assert category["name"] == "Médiation" and category["staff_role_ids"] == (5,)
            assert (await session.get(100)).welcome_message_id == 12345
            draft = CategoryDraft.from_category(category)
            draft.name = "Plaintes et médiation"
            await session.save_category(draft)
            assert (await session.active(2, "report")).label == "Plaintes et médiation"
        with pytest.raises(aiomysql.IntegrityError):
            async with store.ticket_session(1) as session:
                await session.create(101, 2, "report", {"transcript_channel_id": None})
        async with store.ticket_session(999) as foreign:
            assert (await foreign.category("report"))["name"] == "Plaintes"
            assert (await foreign.category("report"))["staff_role_ids"] == ()
            assert await foreign.for_category("report") == []

    asyncio.run(scenario())
