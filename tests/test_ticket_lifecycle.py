"""Ticket deletion, reopening, closed-ticket access and administrator role changes."""

import asyncio
from dataclasses import replace
from datetime import datetime
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from src.commands.support import ticket as command
from src.utils import ticket_controls as controls
from src.utils import ticket_service as service
from src.utils import tickets as store
from test_ticket_claims import assignment, opening_message
from test_ticket_controls import interaction_env
from test_tickets import destination, install_session, ticket


def administrator_role(env):
    role = Mock(spec=discord.Role)
    role.id, role.guild = 7, env.guild
    role.permissions = discord.Permissions(manage_guild=True)
    role.is_default.return_value = False
    env.guild.roles = [role]
    env.admin.roles.append(role)
    env.guild.get_role.side_effect = {1: env.guild.default_role, 5: env.staff_role, 7: role}.get
    return role


@pytest.mark.parametrize("status", ["open", "closed"])
def test_controls_show_reopening_only_on_closed_tickets_and_keep_deletion_available(status):
    async def scenario():
        view = controls.TicketCloseView(None, ticket(status=status))
        assert (view.reopen in view.children) is (status == "closed")
        assert (view.close in view.children) is (status == "open")
        assert view.delete in view.children
        assert view.delete.style == discord.ButtonStyle.danger
        assert view.is_persistent()
        assert len(view.children) <= 5
    asyncio.run(scenario())


def test_delete_button_and_command_offer_the_same_private_confirmation(monkeypatch):
    async def scenario():
        env = interaction_env(monkeypatch)
        env.interaction.user = env.staff
        manager = SimpleNamespace(deletion_preview=AsyncMock(return_value=ticket()), delete=AsyncMock())
        await controls.TicketCloseView(manager).delete.callback(env.interaction)
        group = command.Tickets(manager)
        await group.get_command("delete").callback(group, env.interaction)
        assert manager.deletion_preview.await_count == 2
        manager.delete.assert_not_awaited()
        for call in env.interaction.followup.send.await_args_list:
            assert call.kwargs["ephemeral"]
            assert "archives" in call.kwargs["embed"].description
            assert call.kwargs["view"].owner_id == env.staff.id
    asyncio.run(scenario())


@pytest.mark.parametrize("blocked", [None, "other_user", "other_channel", "other_guild", "cancelled", "expired"])
def test_delete_confirmation_is_bound_to_actor_and_ticket_and_can_only_run_once(monkeypatch, blocked):
    async def scenario():
        env = interaction_env(monkeypatch)
        env.interaction.user = env.staff
        manager = SimpleNamespace(delete=AsyncMock(return_value=(ticket(status="deleted"), None)))
        view = controls.TicketDeleteConfirmation(manager, 3, 1, 10, 1)
        if blocked == "other_user":
            env.interaction.user = env.creator
        elif blocked == "other_channel":
            env.interaction.channel_id = 20
        elif blocked == "other_guild":
            env.interaction.guild_id = 999
        elif blocked == "cancelled":
            await view.cancel.callback(env.interaction)
        elif blocked == "expired":
            view.stop()
        await view.confirm.callback(env.interaction)
        await view.confirm.callback(env.interaction)
        if blocked:
            manager.delete.assert_not_awaited()
        else:
            manager.delete.assert_awaited_once_with(env.interaction, 1)
            assert "archives" in env.interaction.edit_original_response.await_args.kwargs["content"]
    asyncio.run(scenario())


@pytest.mark.parametrize("identity", ["creator", "staff", "admin", "outsider"])
def test_deletion_requires_category_support_or_administration(monkeypatch, identity):
    async def scenario():
        env = destination()
        env.interaction.user = getattr(env, identity)
        session = SimpleNamespace(get=AsyncMock(return_value=ticket()), panels=AsyncMock(return_value=[]))
        install_session(monkeypatch, session)
        if identity in {"staff", "admin"}:
            assert (await service.TicketService().deletion_preview(env.interaction)).id == 1
        else:
            with pytest.raises(store.TicketError):
                await service.TicketService().deletion_preview(env.interaction)
        env.current.delete.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("protected", ["panel", "transcript_channel_id", "logs_channel_id", "permission"])
def test_deletion_protects_configuration_channels_and_checks_bot_permissions(monkeypatch, protected):
    async def scenario():
        env = destination()
        env.interaction.user = env.staff
        panel = {"channel_id": 20}
        if protected == "panel":
            panel["channel_id"] = 10
        elif protected == "permission":
            env.current.permissions_for.side_effect = None
            env.current.permissions_for.return_value = discord.Permissions(view_channel=True)
        else:
            panel[protected] = 10
        session = SimpleNamespace(get=AsyncMock(return_value=ticket()), panels=AsyncMock(return_value=[panel]))
        install_session(monkeypatch, session)
        with pytest.raises(store.TicketError):
            await service.TicketService().deletion_preview(env.interaction)
        env.current.delete.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["stale", "archive"])
def test_stale_confirmation_or_failed_archive_never_deletes_the_channel(monkeypatch, failure):
    async def scenario():
        env = destination()
        env.interaction.user = env.staff
        session = SimpleNamespace(get=AsyncMock(return_value=ticket(status="closed")), panels=AsyncMock(return_value=[]),
                                  event=AsyncMock(), save_transcript=AsyncMock())
        install_session(monkeypatch, session)
        monkeypatch.setattr(service, "build_transcript", AsyncMock(side_effect=store.TicketError("Archive unavailable")))
        with pytest.raises(store.TicketError):
            await service.TicketService().delete(env.interaction, 99 if failure == "stale" else 1)
        env.current.delete.assert_not_awaited()
        session.save_transcript.assert_not_awaited()
    asyncio.run(scenario())


def test_administrators_can_claim_without_category_roles(monkeypatch):
    async def scenario():
        env, _state, _session, _message = assignment(monkeypatch)
        env.interaction.user = env.admin
        claimed = await service.TicketService().assign(env.interaction)
        assert claimed.claimed_by == env.admin.id
        assert env.current.name.endswith("🟢-member-8")
    asyncio.run(scenario())


def test_management_roles_can_write_after_closure_and_revoked_roles_leave_both_permission_snapshots():
    env = destination()
    role = administrator_role(env)
    original = service.private_overwrites(env.guild, env.creator, [env.staff_role])
    original[env.outsider] = service.member_overwrite()
    closed = service.archive_overwrites(env.guild, original, (5,), creator_id=2)
    for target in (role, env.staff_role):
        assert closed[target].view_channel and closed[target].send_messages
        assert closed[target].use_application_commands
    for target in (env.creator, env.outsider):
        assert closed[target].view_channel is False and closed[target].send_messages is False
    saved = ticket(status="closed", admin_role_ids=(7,), saved_overwrites=json.dumps(service.serialize_overwrites(original)))
    role.permissions = discord.Permissions.none()
    updated = service.replace_staff_overwrites(env.guild, saved, closed, [env.staff_role])
    assert role not in updated
    snapshot = json.loads(service.replace_saved_staff(env.guild, saved, [env.staff_role]))
    assert not any(entry["type"] == "role" and entry["id"] == 7 for entry in snapshot)


def test_reopen_button_uses_the_existing_permission_and_duplicate_ticket_checks(monkeypatch):
    async def scenario():
        env = interaction_env(monkeypatch)
        manager = SimpleNamespace(mutate=AsyncMock(return_value=(ticket(), None)))
        await controls.TicketCloseView(manager, ticket(status="closed")).reopen.callback(env.interaction)
        manager.mutate.assert_awaited_once_with(env.interaction, "reopened")
        assert env.interaction.followup.send.await_args.kwargs["ephemeral"]
    asyncio.run(scenario())


def test_closed_long_names_keep_the_claimant_and_lock_within_discord_limits():
    env = destination()
    current = ticket(status="closed", claimed_by=3, claim_emoji="🎯")
    name = service.ticket_channel_name(current, env.guild, "ticket-0001-" + "x" * 90)
    assert name.startswith("ticket-0001-") and "🎯-member-3" in name and name.endswith("-🔒")
    assert len(name.encode("utf-16-le")) // 2 <= 100


@pytest.mark.parametrize("failed_commit", [None, 2, 3])
def test_mysql_lifecycle_retains_archives_and_numbering_and_recovers_failed_channel_deletion(monkeypatch, failed_commit):
    import aiomysql
    from src.core.db_init import init_db

    port = os.getenv("TICKET_TEST_DB_PORT")
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
                for table in ("tickets", "ticket_panels", "ticket_categories", "ticket_sequences"):
                    await cursor.execute(f"DELETE FROM {table}")
        finally:
            db.close()
        env = destination()
        admin_role = administrator_role(env)
        manager = service.TicketService()
        async with store.ticket_session(1) as session:
            category = store.CategoryDraft.from_category(await session.category("report"))
            category.staff_role_ids = (5,)
            await session.save_category(category)
            await session.save_panel(20, 200, 30, None)
        env.interaction.channel, env.interaction.channel_id = env.panel, 20
        opened = await manager.create(env.interaction, "report")
        assert opened.admin_role_ids == (7,)
        channel = env.channels[40]
        assert channel.overwrites[admin_role].view_channel
        env.interaction.channel, env.interaction.channel_id = channel, 40
        env.interaction.user = env.admin
        message = opening_message(env, opened)
        message.id = 4000
        channel.fetch_message = AsyncMock(return_value=message)
        await manager.assign(env.interaction)
        await manager.mutate(env.interaction, "added", user=env.outsider)
        closed, _ = await manager.mutate(env.interaction, "closed", reason="Résolu")
        assert channel.name.endswith("-member-8-🔒")
        assert channel.overwrites[admin_role].send_messages and channel.overwrites[env.staff_role].send_messages
        assert channel.overwrites[env.creator].view_channel is False
        assert channel.overwrites[env.outsider].view_channel is False
        controls_view = controls.previous_ticket_controls(manager, message)
        assert controls_view.reopen in controls_view.children and controls_view.delete in controls_view.children
        # Upgrade an existing archive and then exercise grants and revocations.
        async with store.ticket_session(1) as session:
            await session.execute("UPDATE tickets SET category_version = 0, admin_role_ids = NULL WHERE guild_id = 1")
        channel.overwrites.pop(admin_role)
        channel.overwrites[env.staff_role].send_messages = False
        await manager.sync_categories(env.guild)
        assert channel.overwrites[env.staff_role].send_messages and channel.overwrites[admin_role].send_messages
        admin_role.permissions = discord.Permissions.none()
        await manager.sync_categories(env.guild)
        assert admin_role not in channel.overwrites
        async with store.ticket_session(1) as session:
            assert not (await session.get(40)).admin_role_ids
            assert not any(entry["type"] == "role" and entry["id"] == 7
                           for entry in json.loads((await session.get(40)).saved_overwrites))
        admin_role.permissions = discord.Permissions(manage_guild=True)
        await manager.sync_categories(env.guild)
        assert channel.overwrites[admin_role].send_messages
        async with store.ticket_session(1) as session:
            await session.delete_category("report")
        await manager.sync_categories(env.guild)
        async with store.ticket_session(1) as session:
            archived_category = await session.category("report", include_inactive=True)
            assert not archived_category["is_active"]
            assert (await session.get(40)).category_version == archived_category["version"]
        channel.messages.append(SimpleNamespace(id=501, author=SimpleNamespace(id=3), content="Note après fermeture",
            created_at=datetime(2026, 11, 21), reference=None, attachments=[], embeds=[], stickers=[]))
        await store.record_staff_message(1, 40, env.staff)
        _, transcript = await manager.transcript(env.interaction)
        assert "Note après fermeture" in transcript.decode()
        env.interaction.response = SimpleNamespace(defer=AsyncMock())
        env.interaction.followup = SimpleNamespace(send=AsyncMock())
        await controls_view.reopen.callback(env.interaction)
        assert not channel.name.endswith("🔒") and channel.overwrites[env.outsider].view_channel
        original_delete = channel.delete.side_effect
        channel.delete.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing permissions")
        with pytest.raises(discord.Forbidden):
            await manager.delete(env.interaction, opened.id)
        async with store.ticket_session(1) as session:
            persisted = await session.get(40)
            assert persisted.status == "closed" and await session.active(2, "report") is None
            assert "Note après fermeture" in (await session.latest_transcript(persisted)).decode()
            _, events = await session.history(persisted)
            assert not any(event["action"] == "deleted" for event in events)
        assert 40 in env.channels
        channel.delete.side_effect = original_delete
        if failed_commit:
            connections = 0

            async def failing_connect():
                nonlocal connections
                db = await connect()
                connections += 1
                if connections == failed_commit:
                    db.commit = AsyncMock(side_effect=RuntimeError("Commit failed"))
                return db

            monkeypatch.setattr(store, "get_db_connection", failing_connect)
            with pytest.raises(RuntimeError, match="Commit failed"):
                await manager.delete(env.interaction, opened.id)
            monkeypatch.setattr(store, "get_db_connection", connect)
            assert (40 in env.channels) is (failed_commit == 2)
            async with store.ticket_session(1) as session:
                retained = await session.get(40)
                assert retained.status == "closed" and await session.latest_transcript(retained)
                assert await session.active(2, "report") is None
            if failed_commit == 3:
                return
        await manager.delete(env.interaction, opened.id)
        assert 40 not in env.channels
        async with store.ticket_session(1) as session:
            deleted = await session.get(40)
            assert deleted.status == "deleted" and await session.latest_transcript(deleted)
            staff, events = await session.history(deleted)
            assert {row["user_id"] for row in staff} == {3, 8}
            assert events[-1]["action"] == "deleted" and events[-1]["actor_id"] == 8
            assert await session.next_number() == 2
        async with store.ticket_session(999) as session:
            assert await session.get(40) is None
    asyncio.run(scenario())
