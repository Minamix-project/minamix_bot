"""Personal staff markers and pending-ticket indicators retain names and permissions."""

import asyncio
from dataclasses import replace
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from src.commands.support import ticket as command
from src.utils import ticket_service as service
from src.utils import tickets as store
from test_ticket_claims import opening_message
from test_tickets import category_record, destination, install_session, ticket


@pytest.mark.parametrize("emoji", ["🎯", "🧰", "❤️", "👩🏽‍💻", "🇫🇷", "1️⃣", "ℹ️"])
def test_staff_marker_accepts_single_unicode_emoji_sequences(emoji):
    assert service.validate_staff_emoji(emoji) == emoji


@pytest.mark.parametrize("emoji", ["", "abc", "A🎯", "🎯🔥", "<:staff:123456789012345678>", "🎯/", "⃣"])
def test_staff_marker_rejects_text_and_custom_discord_emoji(emoji):
    with pytest.raises(store.TicketError, match="emoji Unicode"):
        service.validate_staff_emoji(emoji)


def emoji_session(monkeypatch, *, fail_commit=False):
    env = destination()
    env.interaction.user = env.staff
    env.current.name = "ticket-0001-🟢-member-3"
    current = ticket(claimed_by=3, channel_base_name="ticket-0001", claim_base_name="ticket-0001")
    selected = {"emoji": "🟢"}

    async def set_emoji(user_id, emoji):
        selected["emoji"] = emoji or "🟢"

    session = SimpleNamespace(categories=AsyncMock(return_value=[category_record(staff_role_ids=(5,))]),
        set_staff_emoji=AsyncMock(side_effect=set_emoji), for_claimant=AsyncMock(
            side_effect=lambda user_id: [replace(current, claim_emoji=selected["emoji"])]), execute=AsyncMock())
    install_session(monkeypatch, session, fail_commit=fail_commit)
    return env, session


def test_staff_emoji_changes_current_claims_and_reset_restores_green_without_changing_permissions(monkeypatch):
    async def scenario():
        env, session = emoji_session(monkeypatch)
        original = service.serialize_overwrites(env.current.overwrites)
        manager = service.TicketService()
        assert await manager.set_staff_emoji(env.interaction, "🎯") == "🎯"
        assert env.current.name == "ticket-0001-🎯-member-3"
        session.set_staff_emoji.assert_awaited_once_with(3, "🎯")
        assert await manager.set_staff_emoji(env.interaction, None) == "🟢"
        assert env.current.name == "ticket-0001-🟢-member-3"
        assert service.serialize_overwrites(env.current.overwrites) == original
    asyncio.run(scenario())


def test_regular_members_cannot_set_staff_emojis_and_failed_saves_restore_channel_names(monkeypatch):
    async def scenario():
        env, session = emoji_session(monkeypatch, fail_commit=True)
        with pytest.raises(RuntimeError, match="Commit failed"):
            await service.TicketService().set_staff_emoji(env.interaction, "🎯")
        assert env.current.name == "ticket-0001-🟢-member-3"
        env.interaction.user = env.creator
        session.set_staff_emoji.reset_mock()
        with pytest.raises(store.TicketError, match="personnel de support"):
            await service.TicketService().set_staff_emoji(env.interaction, "🎯")
        session.set_staff_emoji.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("status,enabled,claimed,expected", [
    ("open", True, None, "rapport-🔴"), ("open", False, None, "rapport"),
    ("closed", True, None, "rapport-🔒"), ("closed", False, None, "rapport-🔒"),
    ("open", True, 3, "rapport-🎯-member-3"), ("closed", False, 3, "rapport-🎯-member-3-🔒"),
])
def test_pending_marker_only_appears_for_unclaimed_open_claimable_tickets(monkeypatch, status, enabled, claimed, expected):
    async def scenario():
        env = destination()
        env.current.name = "rapport-🔴"
        current = ticket(status=status, claim_enabled=enabled, claimed_by=claimed,
                         channel_base_name="rapport", claim_emoji="🎯")
        session = SimpleNamespace()
        install_session(monkeypatch, session)
        await service.TicketService().sync_ticket_name(env.guild, env.current, current, session, [])
        assert env.current.name == expected
        session.set_channel_base_name.assert_not_awaited()
    asyncio.run(scenario())


def test_pending_marker_preserves_long_base_names_and_custom_emoji_keeps_the_owner_after_it():
    base = "é" * 100
    pending = service.unclaimed_channel_name(base, claimable=True)
    assert pending.endswith("-🔴") and len(pending.encode("utf-16-le")) // 2 <= 100
    env = destination()
    name = service.claimed_channel_name("ticket-0001-" + "a" * 90, env.guild, 3, emoji="👩🏽‍💻")
    assert name.startswith("ticket-0001-") and "-👩🏽‍💻-member-3" in name
    assert len(name.encode("utf-16-le")) // 2 <= 100


def test_emoji_command_only_changes_the_requesting_members_marker_and_replies_privately():
    async def scenario():
        env = destination()
        env.interaction.response = SimpleNamespace(defer=AsyncMock())
        env.interaction.followup = SimpleNamespace(send=AsyncMock())
        manager = SimpleNamespace(set_staff_emoji=AsyncMock(return_value="🎯"))
        group = command.Tickets(manager)
        emoji = group.get_command("emoji")
        assert [parameter.name for parameter in emoji.parameters] == ["emoji"]
        assert not emoji.parameters[0].required
        await emoji.callback(group, env.interaction, "🎯")
        manager.set_staff_emoji.assert_awaited_once_with(env.interaction, "🎯")
        assert env.interaction.followup.send.await_args.kwargs["ephemeral"]
    asyncio.run(scenario())


def test_mysql_markers_preferences_and_admin_release_are_persistent_and_guild_scoped(monkeypatch):
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
                for table in ("tickets", "ticket_panels", "ticket_categories", "ticket_sequences", "ticket_staff_preferences"):
                    await cursor.execute(f"DELETE FROM {table}")
        finally:
            db.close()
        env = destination()
        manager = service.TicketService()
        async with store.ticket_session(1) as session:
            category = store.CategoryDraft.from_category(await session.category("report"))
            category.staff_role_ids = (5,)
            await session.save_category(category)
            await session.save_panel(20, 200, 30, None)
        env.interaction.channel, env.interaction.channel_id = env.panel, 20
        opened = await manager.create(env.interaction, "report")
        channel = env.channels[40]
        assert channel.name == "ticket-0001-🔴"
        env.interaction.channel, env.interaction.channel_id = channel, 40
        env.interaction.user = env.staff
        message = opening_message(env, opened)
        message.id = 4000
        channel.fetch_message = AsyncMock(return_value=message)
        env.panel.fetch_message = AsyncMock(return_value=SimpleNamespace(author=env.guild.me, edit=AsyncMock()))
        original = service.serialize_overwrites(channel.overwrites)
        await manager.set_staff_emoji(env.interaction, "🎯")
        await manager.assign(env.interaction)
        assert channel.name == "ticket-0001-🎯-member-3"

        async def broken_connect():
            db = await connect()
            db.commit = AsyncMock(side_effect=RuntimeError("Commit failed"))
            return db

        monkeypatch.setattr(store, "get_db_connection", broken_connect)
        with pytest.raises(RuntimeError, match="Commit failed"):
            await manager.set_staff_emoji(env.interaction, "🐱")
        monkeypatch.setattr(store, "get_db_connection", connect)
        assert channel.name == "ticket-0001-🎯-member-3"
        async with store.ticket_session(1) as session:
            assert (await session.get(40)).claim_emoji == "🎯"
        await manager.set_staff_emoji(env.interaction, "🧰")
        assert channel.name == "ticket-0001-🧰-member-3"
        env.interaction.user = env.admin
        await manager.assign(env.interaction, release=True)
        assert channel.name == "ticket-0001-🔴"
        assert service.serialize_overwrites(channel.overwrites) == original
        async with store.ticket_session(1) as session:
            released = await session.get(40)
            assert released.claimed_by is None and released.channel_base_name == "ticket-0001"
            _staff, events = await session.history(released)
            assert events[-1]["actor_id"] == env.admin.id and events[-1]["detail"] == "3"
        env.interaction.user = env.staff
        await manager.assign(env.interaction)
        await manager.mutate(env.interaction, "renamed", name="Support RP")
        assert channel.name == "support-rp-🧰-member-3"
        await manager.set_staff_emoji(env.interaction, None)
        assert channel.name == "support-rp-🟢-member-3"
        env.interaction.user = env.admin
        await manager.assign(env.interaction, release=True)
        assert channel.name == "support-rp-🔴"
        async with store.ticket_session(999) as foreign:
            await foreign.set_staff_emoji(3, "🔥")
            await foreign.create(90, 4, "general", {"transcript_channel_id": None})
            await foreign.claim(await foreign.get(90), 3, "foreign")
            assert (await foreign.get(90)).claim_emoji == "🔥"
            assert [item.channel_id for item in await foreign.for_claimant(3)] == [90]
        env.interaction.user = env.staff
        claimed = await manager.assign(env.interaction)
        assert claimed.claim_emoji == "🟢"
        env.interaction.user = env.admin
        await manager.assign(env.interaction, release=True)
        async with store.ticket_session(1) as session:
            draft = store.CategoryDraft.from_category(await session.category("report"))
        draft.claim_enabled = False
        await manager.save_category(env.interaction, draft, lambda: command.TicketPanel(manager))
        assert channel.name == "support-rp"
        draft.version += 1
        draft.claim_enabled = True
        await manager.save_category(env.interaction, draft, lambda: command.TicketPanel(manager))
        assert channel.name == "support-rp-🔴"
        await manager.mutate(env.interaction, "closed", reason="Résolu")
        assert channel.name == "support-rp-🔒"
        await manager.mutate(env.interaction, "reopened")
        assert channel.name == "support-rp-🔴"

    asyncio.run(scenario())
