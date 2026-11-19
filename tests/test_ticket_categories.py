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
from src.utils.tickets import CATEGORY_OPTIONS, MAX_CATEGORIES, CategoryDraft, TicketError
from test_ticket_creation import creation_session
from test_ticket_role_sync import synchronization
from test_ticket_setup import session as setup_session
from test_tickets import category_record, destination, install_session


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
        assert view.draft.claim_enabled is True
        await view.toggle_claim(env.interaction)
        assert view.draft.claim_enabled is False
        context.service.save_category.assert_not_awaited()
        await view.save(env.interaction)
        draft = context.service.save_category.await_args.args[1]
        assert draft.name == "Médiation" and draft.staff_role_ids == ()
        assert draft.claim_enabled is False
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


def test_category_creation_stays_a_draft_until_explicitly_saved(monkeypatch):
    async def scenario():
        env, context = setup_session(monkeypatch)
        records = [category_record()]
        context.service.save_category = AsyncMock()
        context.service.categories = AsyncMock(return_value=records)
        view = editor.CategoryEditor(context, records)
        await view.create(env.interaction)
        assert view.draft is None
        modal = env.interaction.response.send_modal.await_args.args[0]
        modal.name_input._value = "Événements"
        modal.emoji_input._value = "🎉"
        modal.description_input._value = "Organiser un événement"
        modal.welcome_input._value = "Présente ton événement."
        await modal.on_submit(env.interaction)
        assert view.draft.version == 0 and view.draft.category_key == ""
        assert view.draft.staff_role_ids == ()
        context.service.save_category.assert_not_awaited()
        await view.save(env.interaction)
        assert context.service.save_category.await_args.args[1].name == "Événements"
    asyncio.run(scenario())


def test_category_deletion_requires_confirmation_and_can_be_cancelled(monkeypatch):
    async def scenario():
        env, context = setup_session(monkeypatch)
        context.service.delete_category = AsyncMock()
        context.service.categories = AsyncMock(return_value=[])
        view = editor.CategoryEditor(context, [category_record()])
        env.interaction.data = {"values": ["report"]}
        await view.choose(env.interaction)
        await view.ask_delete(env.interaction)
        assert view.delete_target["category_key"] == "report"
        assert "accès" in view.embed(env.interaction).description
        context.service.delete_category.assert_not_awaited()
        await view.cancel_delete(env.interaction)
        context.service.delete_category.assert_not_awaited()
        await view.ask_delete(env.interaction)
        await view.confirm_delete(env.interaction)
        context.service.delete_category.assert_awaited_once_with(env.interaction, "report", 1, context.panel_view_factory)
        assert not view.categories and view.draft is None
        assert not any(isinstance(item, discord.ui.Select) for item in view.children)
        with pytest.raises(TicketError, match="Confirme d'abord"):
            await view.confirm_delete(env.interaction)
        assert context.service.delete_category.await_count == 1
        public_view = command.TicketPanel(None, [])
        assert public_view.children[0].disabled
        assert public_view.children[0].options[0].label == "Aucune catégorie disponible"
    asyncio.run(scenario())


def test_new_categories_get_server_generated_keys_and_respect_the_active_limit(monkeypatch):
    async def scenario():
        env = destination()
        env.interaction.user = env.admin
        draft = CategoryDraft("", "Événements", "🎉", "Organiser un événement", "Présente ton événement.", version=0)
        session = SimpleNamespace(categories=AsyncMock(return_value=[]), create_category=AsyncMock(),
            category=AsyncMock(side_effect=lambda key: {**category_record(), "category_key": key}),
            for_category=AsyncMock(return_value=[]), panels=AsyncMock(return_value=[]), execute=AsyncMock())
        install_session(monkeypatch, session)
        created = await service.TicketService().save_category(env.interaction, draft, lambda: command.TicketPanel(None))
        assert len(created["category_key"]) == 32
        assert draft.category_key == "" and draft.version == 0
        session.create_category.assert_awaited_once_with(created["category_key"], draft)
        session.create_category.reset_mock()
        session.categories.return_value = [category_record() for _ in range(MAX_CATEGORIES)]
        with pytest.raises(TicketError, match="25 catégories"):
            await service.TicketService().save_category(env.interaction, draft, lambda: command.TicketPanel(None))
        session.create_category.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [None, "version", "permission", "commit"])
def test_deletion_updates_menus_but_keeps_ticket_records_and_permissions(monkeypatch, failure):
    async def scenario():
        env = destination()
        env.interaction.user = env.admin if failure != "permission" else env.creator
        record = category_record()
        session = SimpleNamespace(category=AsyncMock(return_value=record),
            categories=AsyncMock(side_effect=lambda: [] if session.delete_category.await_count else [record]),
            delete_category=AsyncMock(), panels=AsyncMock(return_value=[{"channel_id": 20, "message_id": 200}]),
            execute=AsyncMock(), for_category=AsyncMock(), update_category=AsyncMock())
        install_session(monkeypatch, session, fail_commit=failure == "commit")
        panel = SimpleNamespace(author=env.guild.me, edit=AsyncMock())
        env.panel.fetch_message = AsyncMock(return_value=panel)
        manager = service.TicketService()
        if failure:
            with pytest.raises((TicketError, RuntimeError)):
                await manager.delete_category(env.interaction, "report", 0 if failure == "version" else 1,
                                              lambda: command.TicketPanel(None))
        else:
            await manager.delete_category(env.interaction, "report", 1, lambda: command.TicketPanel(None))
            assert panel.edit.await_args.kwargs["view"].children[0].disabled
        session.for_category.assert_not_awaited()
        session.update_category.assert_not_awaited()
        env.current.edit.assert_not_awaited()
        if failure in {"version", "permission"}:
            session.delete_category.assert_not_awaited()
            panel.edit.assert_not_awaited()
        elif failure == "commit":
            assert panel.edit.await_count == 2
            assert not panel.edit.await_args.kwargs["view"].children[0].disabled
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
        async with store.ticket_session(1) as session:
            draft = CategoryDraft("", "Événements", "🎉", "Organiser un événement", "Présente ton événement.", version=0)
            await session.create_category("custom_events", draft)
            custom = await session.category("custom_events")
            assert custom["name"] == "Événements" and custom["staff_role_ids"] == ()
            await session.save_transcript(await session.get(100), 3, b"Original transcript")
            await session.delete_category("report")
        async with store.ticket_session(1) as session:
            assert await session.category("report") is None
            retained = await session.get(100)
            assert retained.label == "Plaintes et médiation" and retained.staff_role_ids == (5,)
            assert await session.latest_transcript(retained) == b"Original transcript"
            assert (await session.active(2, "report")).id == retained.id
            for category in await session.categories():
                await session.delete_category(category["category_key"])
        async with store.ticket_session(1) as session:
            assert await session.categories() == []
            await session.create_category("replacement", draft)
        async with store.ticket_session(1) as session:
            assert [category["category_key"] for category in await session.categories()] == ["replacement"]
            assert (await session.get(100)).label == "Plaintes et médiation"
        async with store.ticket_session(999) as foreign:
            assert len(await foreign.categories()) == 6

    asyncio.run(scenario())
