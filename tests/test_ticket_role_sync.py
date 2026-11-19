"""Panel edits synchronize existing ticket access without breaking archive privacy."""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from src.utils import ticket_service as service
from src.utils import tickets as store
from src.utils.tickets import PanelDraft, TicketError
from test_ticket_setup import panel_record
from test_tickets import destination, install_session, ticket


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
    # The panel may already have been edited before this fix was deployed.
    record = panel_record(staff_role_ids=(6,), message_id=200)
    draft = PanelDraft.from_panel(record)
    message = SimpleNamespace(id=200, author=env.guild.me, embeds=[], edit=AsyncMock())
    env.panel.fetch_message = AsyncMock(return_value=message)
    session = SimpleNamespace(
        panel=AsyncMock(return_value=record), for_panel=AsyncMock(return_value=[current]),
        get=AsyncMock(return_value=None), update_staff=AsyncMock(), save_panel=AsyncMock(return_value=1), execute=AsyncMock(),
    )
    install_session(monkeypatch, session, fail_commit=fail_commit)
    return env, new_role, current, draft, session, message


@pytest.mark.parametrize("keep_previous_role", [False, True])
def test_resaving_a_panel_updates_stale_open_tickets_roles_and_staff_authority(monkeypatch, keep_previous_role):
    async def scenario():
        env, new_role, current, draft, session, _message = synchronization(monkeypatch)
        env.current.overwrites[env.outsider] = discord.PermissionOverwrite(view_channel=False)
        env.current.overwrites[env.staff] = service.member_overwrite()
        if keep_previous_role:
            draft.staff_role_ids = (5, 6)
        original = service.serialize_overwrites(env.current.overwrites)
        await service.TicketService().panel(env.interaction, draft, None)
        session.for_panel.assert_awaited_once_with(draft.id)
        session.update_staff.assert_awaited_once_with(current, draft.staff_role_ids, None)
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
        await service.TicketService().panel(env.interaction, draft, None)
        updated = env.current.overwrites
        assert env.staff_role not in updated
        assert updated[new_role].view_channel is True and updated[new_role].send_messages is False
        assert updated[env.creator].view_channel is False
        # This invited member now belongs to the new support team.
        assert updated[env.outsider].view_channel is True and updated[env.outsider].send_messages is False
        assert updated[env.guild.me].send_messages is True
        snapshot = session.update_staff.await_args.args[2]
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
        finally:
            db.close()
        archived = Mock(spec=discord.TextChannel)
        archived.id, archived.guild = 50, env.guild
        original = dict(env.current.overwrites)
        archived.overwrites = service.archive_overwrites(env.guild, original, (5,), creator_id=env.creator.id)
        archived.permissions_for.return_value = discord.Permissions(manage_channels=True, manage_roles=True)

        async def edit(**kwargs):
            archived.overwrites = kwargs["overwrites"]

        archived.edit = AsyncMock(side_effect=edit)
        env.channels[50] = archived
        async with store.ticket_session(1) as session:
            first_id = await session.save_panel(20, 200, 30, (5,), None)
            second_id = await session.save_panel(20, 201, 30, (5,), None)
            first = await session.panel(first_id)
            await session.create(10, 2, "report", first)
            await session.create(50, 2, "shop", first)
            await session.close(await session.get(50), 8, "Résolu", service.serialize_overwrites(original))
            await session.create(60, 3, "report", await session.panel(second_id))
        draft = PanelDraft.from_panel(first)
        draft.staff_role_ids = (6,)
        await service.TicketService().panel(env.interaction, draft, None)
        async with store.ticket_session(1) as session:
            assert (await session.get(10)).staff_role_ids == (6,)
            closed = await session.get(50)
            assert closed.status == "closed" and closed.staff_role_ids == (6,)
            restored = await service.deserialize_overwrites(env.guild, json.loads(closed.saved_overwrites))
            assert new_role in restored and env.staff_role not in restored
            assert restored[new_role].send_messages is True
            assert (await session.get(60)).staff_role_ids == (5,)
            assert {entry.channel_id for entry in await session.for_panel(first_id)} == {10, 50}
        async with store.ticket_session(999) as foreign:
            assert await foreign.for_panel(first_id) == []
        assert env.current.overwrites[new_role].send_messages is True
        assert archived.overwrites[new_role].send_messages is False
        assert archived.overwrites[env.creator].view_channel is False

    asyncio.run(scenario())


def test_panel_sync_preserves_unrelated_overwrites_and_hides_former_staff_in_archives(monkeypatch):
    async def scenario():
        env, _new_role, _current, draft, _session, _message = synchronization(monkeypatch, closed=True)
        env.current.overwrites[env.staff] = service.member_overwrite()
        unrelated = Mock(spec=discord.Role)
        unrelated.id = 7
        env.current.overwrites[unrelated] = discord.PermissionOverwrite(view_channel=False, attach_files=False)
        await service.TicketService().panel(env.interaction, draft, None)
        assert env.current.overwrites[env.staff].view_channel is False
        assert env.current.overwrites[unrelated].view_channel is False
        assert env.current.overwrites[unrelated].attach_files is False
    asyncio.run(scenario())


def test_failed_panel_commit_restores_existing_ticket_permissions(monkeypatch):
    async def scenario():
        env, _new_role, _current, draft, session, message = synchronization(monkeypatch, fail_commit=True)
        original = service.serialize_overwrites(env.current.overwrites)
        with pytest.raises(RuntimeError, match="Commit failed"):
            await service.TicketService().panel(env.interaction, draft, None)
        assert service.serialize_overwrites(env.current.overwrites) == original
        assert env.current.edit.await_count == 2
        assert message.edit.await_count == 2
        session.update_staff.assert_awaited_once()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["permissions", "http"])
def test_inaccessible_ticket_does_not_leave_other_tickets_partially_updated(monkeypatch, failure):
    async def scenario():
        env, _new_role, current, draft, session, message = synchronization(monkeypatch)
        other = Mock(spec=discord.TextChannel)
        other.id, other.guild = 50, env.guild
        other.overwrites = dict(env.current.overwrites)
        other.permissions_for.return_value = discord.Permissions(manage_channels=True, manage_roles=True)
        other.edit = AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Denied"))
        env.channels[50] = other
        session.for_panel.return_value.append(ticket(id=2, channel_id=50, panel_id=1))
        if failure == "permissions":
            other.permissions_for.return_value = discord.Permissions.none()
        original = service.serialize_overwrites(env.current.overwrites)
        with pytest.raises((TicketError, discord.Forbidden)):
            await service.TicketService().panel(env.interaction, draft, None)
        assert service.serialize_overwrites(env.current.overwrites) == original
        message.edit.assert_not_awaited()
        session.save_panel.assert_not_awaited()
        if failure == "permissions":
            env.current.edit.assert_not_awaited()
        else:
            session.update_staff.assert_awaited_once_with(current, (6,), None)
            assert env.current.edit.await_count == 2
    asyncio.run(scenario())


def test_unchanged_roles_skip_edits_and_deleted_ticket_channels_are_ignored(monkeypatch):
    async def scenario():
        env, _new_role, current, draft, session, _message = synchronization(monkeypatch)
        current.staff_role_ids = (6,)
        session.for_panel.return_value.append(ticket(id=2, channel_id=50, panel_id=1))
        env.guild.fetch_channel = AsyncMock(
            side_effect=discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Missing"),
        )
        await service.TicketService().panel(env.interaction, draft, None)
        env.current.edit.assert_not_awaited()
        session.update_staff.assert_not_awaited()
        env.guild.fetch_channel.assert_awaited_once_with(50)
    asyncio.run(scenario())
