"""Exclusive ticket assignment without permission changes or administrator overrides."""

import asyncio
from dataclasses import replace
from datetime import datetime
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from src.commands.support import ticket as command
from src.utils import ticket_controls as controls
from src.utils import ticket_service as service
from src.utils import tickets as store
from test_tickets import category_record, destination, install_session, ticket


def opening_message(env, current):
    view = controls.TicketCloseView(None, current)
    message = SimpleNamespace(id=1000, author=env.guild.me,
        embeds=[discord.Embed(title="Ancien accueil")],
        components=[discord.ActionRow(row) for row in view.to_components()], delete=AsyncMock())

    async def edit(**kwargs):
        if "embed" in kwargs:
            message.embeds = [kwargs["embed"]]
        if "embeds" in kwargs:
            message.embeds = kwargs["embeds"]
        if "view" in kwargs:
            message.components = [discord.ActionRow(row) for row in kwargs["view"].to_components()]

    message.edit = AsyncMock(side_effect=edit)
    return message


def assignment(monkeypatch, *, fail_commit=False, **changes):
    env = destination()
    env.interaction.user = env.staff
    env.current.name = "ticket-0001"
    state = {"ticket": ticket(welcome_message_id=1000, **changes)}
    message = opening_message(env, state["ticket"])
    env.current.fetch_message = AsyncMock(return_value=message)

    async def claim(current, actor_id, base_name):
        state["ticket"] = replace(current, claimed_by=actor_id, claimed_at=datetime(2026, 11, 19), claim_base_name=base_name)

    async def release(current, actor_id):
        state["ticket"] = replace(current, claimed_by=None, claimed_at=None, claim_base_name=None)

    async def set_base(current, name):
        state["ticket"] = replace(current, claim_base_name=name)

    session = SimpleNamespace(get=AsyncMock(side_effect=lambda channel_id: state["ticket"]),
        category=AsyncMock(return_value=category_record(staff_role_ids=(5,))), claim=AsyncMock(side_effect=claim),
        release=AsyncMock(side_effect=release), set_claim_base_name=AsyncMock(side_effect=set_base), event=AsyncMock())
    install_session(monkeypatch, session, fail_commit=fail_commit)
    return env, state, session, message


def test_claim_is_exclusive_and_owner_release_restores_the_original_name_without_changing_access(monkeypatch):
    async def scenario():
        env, state, session, message = assignment(monkeypatch)
        manager = service.TicketService()
        permissions = service.serialize_overwrites(env.current.overwrites)
        claimed = await manager.assign(env.interaction)
        assert claimed.claimed_by == 3 and claimed.claimed_at
        assert env.current.name == "ticket-0001-🟢-member-3"
        fields = {field.name: field.value for field in message.embeds[0].fields}
        assert "<@3>" in fields["Responsable"]
        assert controls.previous_ticket_controls(manager, message).claim.disabled
        session.event.assert_awaited_once_with(claimed, 3, "claimed", staff=True)
        env.creator.roles.append(env.staff_role)
        env.interaction.user = env.creator
        with pytest.raises(store.TicketError, match="déjà pris en charge"):
            await manager.assign(env.interaction)
        env.admin.roles.append(env.staff_role)
        env.interaction.user = env.admin
        with pytest.raises(store.TicketError, match="déjà pris en charge"):
            await manager.assign(env.interaction)
        with pytest.raises(store.TicketError, match="Seul le responsable"):
            await manager.assign(env.interaction, release=True)
        assert state["ticket"].claimed_by == 3
        env.interaction.user = env.staff
        env.staff.roles = [env.guild.default_role]
        released = await manager.assign(env.interaction, release=True)
        assert released.claimed_by is None and released.claimed_at is None
        assert env.current.name == "ticket-0001"
        assert service.serialize_overwrites(env.current.overwrites) == permissions
        assert all(set(call.kwargs) <= {"name", "reason"} for call in env.current.edit.await_args_list)
        assert not any(field.name == "Responsable" for field in message.embeds[0].fields)
    asyncio.run(scenario())


@pytest.mark.parametrize("identity", ["creator", "admin", "outsider"])
def test_members_without_a_category_role_cannot_claim_even_with_admin_permissions(monkeypatch, identity):
    async def scenario():
        env, _state, session, message = assignment(monkeypatch)
        env.interaction.user = getattr(env, identity)
        with pytest.raises(store.TicketError):
            await service.TicketService().assign(env.interaction)
        session.claim.assert_not_awaited()
        env.current.edit.assert_not_awaited()
        message.edit.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("changes", [{"claim_enabled": False}, {"status": "closed"}])
def test_disabled_or_closed_tickets_cannot_be_claimed(monkeypatch, changes):
    async def scenario():
        env, _state, session, _message = assignment(monkeypatch, **changes)
        with pytest.raises(store.TicketError):
            await service.TicketService().assign(env.interaction)
        session.claim.assert_not_awaited()
        env.current.edit.assert_not_awaited()
    asyncio.run(scenario())


def test_claim_permissions_follow_current_category_roles_instead_of_stale_ticket_snapshots(monkeypatch):
    async def scenario():
        env, _state, session, _message = assignment(monkeypatch)
        session.category.return_value = category_record(staff_role_ids=(6,))
        with pytest.raises(store.TicketError, match="rôles de support"):
            await service.TicketService().assign(env.interaction)
        session.claim.assert_not_awaited()
    asyncio.run(scenario())


def test_owner_can_release_after_claiming_is_disabled_and_others_cannot(monkeypatch):
    async def scenario():
        env, _state, session, _message = assignment(monkeypatch, claim_enabled=False, status="closed",
            claimed_by=3, claimed_at=datetime(2026, 11, 19), claim_base_name="rapport-personnalisé")
        view = controls.TicketCloseView(None, await session.get(10))
        assert view.claim not in view.children and view.release in view.children
        assert view.close.disabled
        await service.TicketService().assign(env.interaction, release=True)
        assert env.current.name == "rapport-personnalisé"
    asyncio.run(scenario())


def test_renaming_a_claimed_ticket_keeps_the_marker_and_release_uses_the_new_base_name(monkeypatch):
    async def scenario():
        env, _state, _session, _message = assignment(monkeypatch)
        manager = service.TicketService()
        await manager.assign(env.interaction)
        await manager.mutate(env.interaction, "renamed", name="Support RP")
        assert env.current.name == "support-rp-🟢-member-3"
        await manager.assign(env.interaction, release=True)
        assert env.current.name == "support-rp"
    asyncio.run(scenario())


def test_failed_claim_commit_restores_channel_name_and_opening_message(monkeypatch):
    async def scenario():
        env, _state, _session, message = assignment(monkeypatch, fail_commit=True)
        original = message.embeds[0].to_dict()
        with pytest.raises(RuntimeError, match="Commit failed"):
            await service.TicketService().assign(env.interaction)
        assert env.current.name == "ticket-0001"
        assert message.embeds[0].to_dict() == original
        view = controls.previous_ticket_controls(None, message)
        assert not view.claim.disabled and view.release not in view.children
    asyncio.run(scenario())


def test_claim_recreates_controls_when_the_original_welcome_was_deleted(monkeypatch):
    async def scenario():
        env, _state, session, message = assignment(monkeypatch)
        env.current.fetch_message.side_effect = discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Missing")
        message.id = 2000
        env.current.send.return_value = message
        claimed = await service.TicketService().assign(env.interaction)
        sent = env.current.send.await_args.kwargs
        assert "<@3>" in next(field.value for field in sent["embed"].fields if field.name == "Responsable")
        assert sent["view"].release in sent["view"].children
        assert sent["allowed_mentions"].to_dict()["parse"] == []
        session.set_welcome_message.assert_awaited_once_with(claimed, 2000)
    asyncio.run(scenario())


@pytest.mark.parametrize("release", [False, True])
def test_buttons_and_commands_use_the_same_private_assignment_path(release):
    async def scenario():
        env = destination()
        env.interaction.response = SimpleNamespace(defer=AsyncMock())
        env.interaction.followup = SimpleNamespace(send=AsyncMock())
        manager = SimpleNamespace(assign=AsyncMock(return_value=ticket()))
        view = controls.TicketCloseView(manager)
        await (view.release if release else view.claim).callback(env.interaction)
        group = command.Tickets(manager)
        action = group.get_command("release" if release else "claim")
        await action.callback(group, env.interaction)
        assert manager.assign.await_count == 2
        assert all(call.kwargs == {"release": release} for call in manager.assign.await_args_list)
        assert all(call.kwargs["ephemeral"] for call in env.interaction.followup.send.await_args_list)
    asyncio.run(scenario())


def test_claim_name_keeps_number_order_and_fits_discord_limits_for_unicode_names():
    env = destination()
    env.staff.display_name = "🟢 !!!"
    name = service.claimed_channel_name("ticket-0001", env.guild, 3)
    assert name == "ticket-0001-🟢-3"
    env.staff.display_name = "Équipe" * 40
    name = service.claimed_channel_name("ticket-0001-" + "x" * 80, env.guild, 3)
    assert name.startswith("ticket-0001-") and "🟢" in name
    assert len(name.encode("utf-16-le")) // 2 <= 100


def test_mysql_claims_are_exclusive_persistent_and_follow_the_category_toggle(monkeypatch):
    import aiomysql
    from src.core.db_init import init_db

    port = os.getenv("TICKET_TEST_DB_PORT") or os.getenv("REMINDER_TEST_DB_PORT")
    if not port:
        pytest.skip("Requires a disposable MySQL test database")

    async def connect():
        return await aiomysql.connect(host="127.0.0.1", port=int(port), user="root", password="",
                                     db="reminder_test", autocommit=True, charset="utf8mb4")

    monkeypatch.setattr(store, "get_db_connection", connect)

    async def scenario():
        db = await connect()
        try:
            await init_db(db)
            async with db.cursor() as cursor:
                await cursor.execute("DELETE FROM tickets")
                await cursor.execute("DELETE FROM ticket_panels")
                await cursor.execute("DELETE FROM ticket_categories")
                await cursor.execute("DELETE FROM ticket_sequences")
        finally:
            db.close()
        env = destination()
        manager = service.TicketService()
        async with store.ticket_session(1) as session:
            categories = await session.categories()
            assert all(category["claim_enabled"] for category in categories)
            category = store.CategoryDraft.from_category(await session.category("report"))
            category.staff_role_ids = (5,)
            await session.save_category(category)
            await session.save_panel(20, 200, 30, None)
        env.interaction.channel, env.interaction.channel_id = env.panel, 20
        opened = await manager.create(env.interaction, "report")
        env.interaction.channel, env.interaction.channel_id = env.channels[40], 40
        message = opening_message(env, opened)
        message.id = 4000
        env.channels[40].fetch_message = AsyncMock(return_value=message)
        env.panel.fetch_message = AsyncMock(return_value=SimpleNamespace(author=env.guild.me, edit=AsyncMock()))
        env.creator.roles.append(env.staff_role)
        first = SimpleNamespace(**{**vars(env.interaction), "user": env.staff})
        second = SimpleNamespace(**{**vars(env.interaction), "user": env.creator})
        permissions = service.serialize_overwrites(env.channels[40].overwrites)
        results = await asyncio.gather(manager.assign(first), manager.assign(second), return_exceptions=True)
        winners = [result for result in results if isinstance(result, store.Ticket)]
        assert len(winners) == 1
        assert len([result for result in results if isinstance(result, store.TicketError)]) == 1
        claimed = winners[0]
        async with store.ticket_session(1) as session:
            persisted = await session.get(40)
            assert persisted.claimed_by == claimed.claimed_by and persisted.claimed_at
            assert persisted.claim_base_name == "ticket-0001"
        env.interaction.user = env.admin
        with pytest.raises(store.TicketError, match="Seul le responsable"):
            await manager.assign(env.interaction, release=True)
        env.interaction.user = env.guild.get_member(claimed.claimed_by)
        released = await manager.assign(env.interaction, release=True)
        assert released.claimed_by is None and env.channels[40].name == "ticket-0001"
        assert service.serialize_overwrites(env.channels[40].overwrites) == permissions
        async with store.ticket_session(1) as session:
            _staff, events = await session.history(released)
            assert [event["action"] for event in events] == ["created", "claimed", "released"]
            draft = store.CategoryDraft.from_category(await session.category("report"))
        draft.claim_enabled = False
        env.interaction.user = env.admin
        await manager.save_category(env.interaction, draft, lambda: command.TicketPanel(manager))
        async with store.ticket_session(1) as session:
            assert (await session.get(40)).claim_enabled == 0
        assert "aurum:tickets:claim:v1" not in {
            item.custom_id for row in message.components for item in row.children
        }
        env.interaction.user = env.staff
        with pytest.raises(store.TicketError, match="désactivée"):
            await manager.assign(env.interaction)

    asyncio.run(scenario())


def test_mysql_claim_migration_enables_existing_categories_and_preserves_existing_tickets(monkeypatch, tmp_path):
    import aiomysql
    from pathlib import Path
    from src.core import schema_migrations
    from src.core.db_init import init_db

    port = os.getenv("TICKET_TEST_DB_PORT") or os.getenv("REMINDER_TEST_DB_PORT")
    if not port:
        pytest.skip("Requires a disposable MySQL test database")
    current_migrations = Path("src/migrations")
    legacy_migrations = tmp_path / "legacy_migrations"
    legacy_migrations.mkdir()
    for path in current_migrations.glob("*.sql"):
        if path.name < "0019":
            (legacy_migrations / path.name).write_text(path.read_text())
    monkeypatch.setattr(schema_migrations, "MIGRATIONS_DIR", legacy_migrations)

    async def scenario():
        admin = await aiomysql.connect(host="127.0.0.1", port=int(port), user="root", password="", autocommit=True)
        try:
            async with admin.cursor() as cursor:
                await cursor.execute("CREATE DATABASE ticket_claim_upgrade_test CHARACTER SET utf8mb4")
            db = await aiomysql.connect(host="127.0.0.1", port=int(port), user="root", password="",
                                       db="ticket_claim_upgrade_test", autocommit=True, charset="utf8mb4")
            try:
                await init_db(db)
                async with db.cursor() as cursor:
                    await cursor.execute(
                        "INSERT INTO ticket_categories "
                        "(guild_id, category_key, name, emoji, description, welcome, staff_role_ids, version, position) "
                        "VALUES (1, 'report', 'Médiation', '⚖️', 'Description', 'Accueil', JSON_ARRAY(5), 7, 0)"
                    )
                    await cursor.execute(
                        "INSERT INTO tickets "
                        "(guild_id, channel_id, creator_id, category, staff_role_ids, ticket_number, category_version) "
                        "VALUES (1, 10, 2, 'report', JSON_ARRAY(5), 1, 7)"
                    )
                monkeypatch.setattr(schema_migrations, "MIGRATIONS_DIR", current_migrations)
                await init_db(db)
                await init_db(db)
                async with db.cursor() as cursor:
                    await cursor.execute("SELECT claim_enabled, version, name FROM ticket_categories WHERE guild_id = 1")
                    assert await cursor.fetchone() == (1, 8, "Médiation")
                    await cursor.execute("SELECT claimed_by, claimed_at, claim_base_name, category_version, ticket_number FROM tickets")
                    assert await cursor.fetchone() == (None, None, None, 7, 1)
            finally:
                db.close()
        finally:
            async with admin.cursor() as cursor:
                await cursor.execute("DROP DATABASE ticket_claim_upgrade_test")
            admin.close()

    asyncio.run(scenario())
