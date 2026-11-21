"""Category edits synchronize all associated tickets without breaking archive privacy."""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from src.utils import ticket_service as service
from src.utils import tickets as store
from src.utils.tickets import CategoryDraft, TicketError
from src.commands.support.ticket import TicketPanel
from test_tickets import category_record, destination, install_session, ticket


def synchronization(monkeypatch, *, closed=False, fail_commit=False):
    env = destination()
    env.interaction.user = env.admin
    new_role = Mock(spec=discord.Role)
    new_role.id, new_role.guild, new_role.managed = 6, env.guild, False
    new_role.is_default.return_value = False
    env.guild.get_role.side_effect = {1: env.guild.default_role, 5: env.staff_role, 6: new_role}.get
    env.outsider.roles.append(new_role)
    env.current.overwrites[env.outsider] = service.member_overwrite()
    original = service.serialize_overwrites(env.current.overwrites)
    current = ticket(
        panel_id=1, status="closed" if closed else "open",
        saved_overwrites=json.dumps(original) if closed else None,
    )
    if closed:
        env.current.overwrites = service.archive_overwrites(
            env.guild, env.current.overwrites, current.staff_role_ids, creator_id=current.creator_id,
        )
    record = category_record(staff_role_ids=(5,))
    draft = CategoryDraft.from_category({**record, "staff_role_ids": (6,)})
    message = SimpleNamespace(id=200, author=env.guild.me, embeds=[], edit=AsyncMock())
    current.welcome_message_id = 200
    env.current.fetch_message = AsyncMock(return_value=message)
    session = SimpleNamespace(
        category=AsyncMock(side_effect=lambda key: {**record, "name": draft.name, "emoji": draft.emoji,
            "description": draft.description, "welcome": draft.welcome, "staff_role_ids": draft.staff_role_ids,
            "version": 2 if session.save_category.await_count else 1}),
        categories=AsyncMock(return_value=[record]), for_category=AsyncMock(return_value=[current]),
        panels=AsyncMock(return_value=[]), update_category=AsyncMock(), save_category=AsyncMock(), execute=AsyncMock(),
    )
    install_session(monkeypatch, session, fail_commit=fail_commit)
    return env, new_role, current, draft, session, message


@pytest.mark.parametrize("keep_previous_role", [False, True])
def test_category_roles_update_existing_tickets_and_staff_authority(monkeypatch, keep_previous_role):
    async def scenario():
        env, new_role, current, draft, session, _message = synchronization(monkeypatch)
        env.current.overwrites[env.outsider] = discord.PermissionOverwrite(view_channel=False)
        env.current.overwrites[env.staff] = service.member_overwrite()
        if keep_previous_role:
            draft.staff_role_ids = (5, 6)
        original = service.serialize_overwrites(env.current.overwrites)
        await service.TicketService().save_category(env.interaction, draft, lambda: TicketPanel(None))
        session.for_category.assert_awaited_once_with(draft.category_key)
        assert session.update_category.await_args.args[1]["staff_role_ids"] == draft.staff_role_ids
        assert (env.staff_role in env.current.overwrites) is keep_previous_role
        assert env.current.overwrites[new_role].view_channel
        assert env.current.overwrites[new_role].send_messages
        assert env.current.overwrites[env.creator].view_channel
        assert env.current.overwrites[env.outsider].view_channel
        assert env.current.overwrites[env.staff].view_channel
        assert env.current.overwrites[env.guild.default_role].view_channel is False
        assert env.current.overwrites[env.guild.me].manage_roles
        current.staff_role_ids = draft.staff_role_ids
        env.interaction.user = env.outsider
        assert service.require_access(env.interaction, current, staff_only=True)
        env.interaction.user = env.staff
        if keep_previous_role:
            assert service.require_access(env.interaction, current, staff_only=True)
        else:
            with pytest.raises(TicketError, match="personnel autorisé"):
                service.require_access(env.interaction, current, staff_only=True)
        assert {entry["id"] for entry in original} != set(target.id for target in env.current.overwrites)
    asyncio.run(scenario())


def test_closed_ticket_sync_keeps_participants_hidden_and_updates_reopening_roles(monkeypatch):
    async def scenario():
        env, new_role, current, draft, session, _message = synchronization(monkeypatch, closed=True)
        env.creator.roles.append(new_role)
        # Preserve an uncached participant in the reopening snapshot.
        saved = json.loads(current.saved_overwrites)
        for entry in saved:
            if entry["type"] == "member" and entry["id"] == env.outsider.id:
                entry.update(allow=0, deny=discord.Permissions(view_channel=True).value)
        saved.append({"id": 12345, "type": "member", "allow": 1024, "deny": 0})
        current.saved_overwrites = json.dumps(saved)
        await service.TicketService().save_category(env.interaction, draft, lambda: TicketPanel(None))
        updated = env.current.overwrites
        assert env.staff_role not in updated
        assert updated[new_role].view_channel is True and updated[new_role].send_messages is True
        assert updated[env.creator].view_channel is True
        # This invited member now belongs to the new support team.
        assert updated[env.outsider].view_channel is True and updated[env.outsider].send_messages is True
        assert updated[env.guild.me].send_messages is True
        snapshot = session.update_category.await_args.args[2]
        entries = json.loads(snapshot)
        assert any(entry["id"] == 12345 for entry in entries)
        assert not any(entry["type"] == "role" and entry["id"] == 5 for entry in entries)
        # Avoid resolving the synthetic uncached participant in this test.
        restored = await service.deserialize_overwrites(env.guild, [entry for entry in entries if entry["id"] != 12345])
        assert restored[new_role].send_messages is True
        assert restored[env.creator].view_channel is True
        assert restored[env.outsider].view_channel is True
    asyncio.run(scenario())


def test_mysql_panel_role_sync_updates_only_attached_tickets_and_persists_archive_permissions(monkeypatch):
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

    async def scenario():
        env, new_role, _current, _draft, _session, _message = synchronization(monkeypatch)
        monkeypatch.setattr(store, "get_db_connection", connect)
        monkeypatch.setattr(service, "ticket_session", store.ticket_session)
        db = await connect()
        try:
            await init_db(db)
            async with db.cursor() as cursor:
                await cursor.execute("DELETE FROM tickets")
                await cursor.execute("DELETE FROM ticket_panels")
                await cursor.execute("DELETE FROM ticket_categories")
        finally:
            db.close()
        archived = Mock(spec=discord.TextChannel)
        archived.id, archived.guild = 50, env.guild
        archived.name = "archive-personnalisee"
        archived.topic = None
        archived.history = env.current.history
        original = dict(env.current.overwrites)
        archived.overwrites = service.archive_overwrites(env.guild, original, (5,), creator_id=env.creator.id)
        archived.permissions_for.return_value = discord.Permissions(manage_channels=True, manage_roles=True)

        async def edit(**kwargs):
            for key in ("name", "topic", "overwrites"):
                if key in kwargs:
                    setattr(archived, key, kwargs[key])

        archived.edit = AsyncMock(side_effect=edit)
        env.channels[50] = archived
        env.panel.fetch_message = AsyncMock(return_value=SimpleNamespace(author=env.guild.me, edit=AsyncMock()))
        async with store.ticket_session(1) as session:
            first_id = await session.save_panel(20, 200, 30, None)
            second_id = await session.save_panel(20, 201, 30, None)
            first = await session.panel(first_id)
            await session.create(50, 2, "report", first, staff_role_ids=(5,))
            await session.close(await session.get(50), 8, "Résolu", service.serialize_overwrites(original))
            await session.create(10, 2, "report", await session.panel(second_id), staff_role_ids=(5,))
            await session.create(60, 3, "general", first, staff_role_ids=(5,))
            original_category = await session.category("report")
        draft = CategoryDraft.from_category(original_category)
        draft.staff_role_ids = (6,)
        await service.TicketService().save_category(env.interaction, draft, lambda: TicketPanel(None))
        async with store.ticket_session(1) as session:
            assert (await session.get(10)).staff_role_ids == (6,)
            closed = await session.get(50)
            assert closed.status == "closed" and closed.staff_role_ids == (6,)
            restored = await service.deserialize_overwrites(env.guild, json.loads(closed.saved_overwrites))
            assert new_role in restored and env.staff_role not in restored
            assert restored[new_role].send_messages is True
            assert (await session.get(60)).staff_role_ids == (5,)
            assert {entry.channel_id for entry in await session.for_category("report")} == {10, 50}
        async with store.ticket_session(999) as foreign:
            assert await foreign.for_category("report") == []
        assert env.current.overwrites[new_role].send_messages is True
        assert archived.overwrites[new_role].send_messages is True
        assert archived.overwrites[env.creator].view_channel is False

    asyncio.run(scenario())


def test_category_sync_preserves_unrelated_overwrites_and_hides_former_staff_in_archives(monkeypatch):
    async def scenario():
        env, _new_role, _current, draft, _session, _message = synchronization(monkeypatch, closed=True)
        env.current.overwrites[env.staff] = service.member_overwrite()
        unrelated = Mock(spec=discord.Role)
        unrelated.id = 7
        env.current.overwrites[unrelated] = discord.PermissionOverwrite(view_channel=False, attach_files=False)
        await service.TicketService().save_category(env.interaction, draft, lambda: TicketPanel(None))
        assert env.current.overwrites[env.staff].view_channel is False
        assert env.current.overwrites[unrelated].view_channel is False
        assert env.current.overwrites[unrelated].attach_files is False
    asyncio.run(scenario())


def test_failed_category_commit_restores_existing_ticket_permissions(monkeypatch):
    async def scenario():
        env, _new_role, _current, draft, session, message = synchronization(monkeypatch, fail_commit=True)
        original = service.serialize_overwrites(env.current.overwrites)
        with pytest.raises(RuntimeError, match="Commit failed"):
            await service.TicketService().save_category(env.interaction, draft, lambda: TicketPanel(None))
        assert service.serialize_overwrites(env.current.overwrites) == original
        assert sum("overwrites" in call.kwargs for call in env.current.edit.await_args_list) == 2
        assert message.edit.await_count == 2
        session.update_category.assert_awaited_once()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["permissions", "http"])
def test_inaccessible_ticket_does_not_leave_other_tickets_partially_updated(monkeypatch, failure):
    async def scenario():
        env, _new_role, current, draft, session, message = synchronization(monkeypatch)
        other = Mock(spec=discord.TextChannel)
        other.id, other.guild = 50, env.guild
        other.name = "ticket-0050"
        other.overwrites = dict(env.current.overwrites)
        other.history = env.current.history
        other.topic = None
        other.permissions_for.return_value = discord.Permissions(manage_channels=True, manage_roles=True)
        other.edit = AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Denied"))
        env.channels[50] = other
        session.for_category.return_value.append(ticket(id=2, channel_id=50, panel_id=1))
        if failure == "permissions":
            other.permissions_for.return_value = discord.Permissions.none()
        original = service.serialize_overwrites(env.current.overwrites)
        with pytest.raises((TicketError, discord.Forbidden)):
            await service.TicketService().save_category(env.interaction, draft, lambda: TicketPanel(None))
        assert service.serialize_overwrites(env.current.overwrites) == original
        assert session.save_category.await_count == 1
        if failure == "permissions":
            message.edit.assert_not_awaited()
            env.current.edit.assert_not_awaited()
        else:
            assert message.edit.await_count == 2
            assert session.update_category.await_args.args[0] == current
            assert session.update_category.await_args.args[1]["staff_role_ids"] == (6,)
            assert sum("overwrites" in call.kwargs for call in env.current.edit.await_args_list) == 2
    asyncio.run(scenario())


def test_unchanged_roles_skip_edits_and_deleted_ticket_channels_are_ignored(monkeypatch):
    async def scenario():
        env, _new_role, current, draft, session, _message = synchronization(monkeypatch)
        current.staff_role_ids = (6,)
        current.category_version = 2
        session.for_category.return_value.append(ticket(id=2, channel_id=50, panel_id=1))
        env.guild.fetch_channel = AsyncMock(
            side_effect=discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Missing"),
        )
        await service.TicketService().save_category(env.interaction, draft, lambda: TicketPanel(None))
        env.current.edit.assert_not_awaited()
        session.update_category.assert_not_awaited()
        env.guild.fetch_channel.assert_awaited_once_with(50)
    asyncio.run(scenario())
