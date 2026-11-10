"""Ticket access boundaries, persistent interactions and failure recovery."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
from discord.ext import commands
import pytest

from src.commands.support import ticket as command
from src.utils import ticket_service as service
from src.utils import tickets as store


def ticket(**changes):
    value = store.Ticket(
        1, 1, 10, 2, "report", 5, None, None, "open", datetime(2026, 11, 10), None, None, None, None, 2
    )
    return replace(value, **changes)


def destination():
    guild = Mock(spec=discord.Guild)
    guild.id, guild.filesize_limit = 1, 10 * 1024 * 1024
    everyone = Mock(spec=discord.Role)
    everyone.id, everyone.guild = 1, guild
    staff_role = Mock(spec=discord.Role)
    staff_role.id, staff_role.guild, staff_role.managed = 5, guild, False
    staff_role.is_default.return_value = False

    def member(user_id, *, staff=False, admin=False):
        value = Mock(spec=discord.Member)
        value.id, value.guild, value.bot = user_id, guild, False
        value.roles = [everyone, staff_role] if staff else [everyone]
        value.guild_permissions = discord.Permissions(manage_guild=admin)
        return value

    creator, staff, outsider, admin, bot = (
        member(2),
        member(3, staff=True),
        member(4),
        member(8, admin=True),
        member(99),
    )
    guild.me, guild.default_role = bot, everyone
    members = {value.id: value for value in (creator, staff, outsider, admin, bot)}
    guild.get_role.side_effect = lambda role_id: {1: everyone, 5: staff_role}.get(role_id)
    guild.get_member.side_effect = members.get
    guild.fetch_member = AsyncMock(side_effect=lambda user_id: members[user_id])
    channels = {}
    guild.get_channel.side_effect = channels.get

    def channel(channel_id):
        value = Mock(spec=discord.TextChannel)
        value.id, value.guild, value.name, value.mention = channel_id, guild, f"ticket-{channel_id}", f"<#{channel_id}>"
        value.overwrites = service.private_overwrites(guild, creator, staff_role)

        def permissions_for(target):
            overwrite = value.overwrites.get(target)
            visible = target.id != outsider.id
            if overwrite and overwrite.view_channel is not None:
                visible = overwrite.view_channel
            return discord.Permissions(
                view_channel=visible,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
                manage_channels=True,
                manage_roles=True,
            )

        async def edit(**kwargs):
            if "overwrites" in kwargs:
                value.overwrites = kwargs["overwrites"]
            if "name" in kwargs:
                value.name = kwargs["name"]
            return value

        async def delete(**kwargs):
            channels.pop(channel_id, None)

        async def history(**kwargs):
            for message in value.messages[: kwargs.get("limit", len(value.messages))]:
                yield message

        value.messages = []
        value.permissions_for.side_effect = permissions_for
        value.edit, value.delete, value.send = AsyncMock(side_effect=edit), AsyncMock(side_effect=delete), AsyncMock()
        value.history = history
        channels[channel_id] = value
        return value

    current, panel = channel(10), channel(20)
    category = Mock(spec=discord.CategoryChannel)
    category.id, category.guild, category.channels = 30, guild, []
    category.permissions_for.return_value = discord.Permissions(manage_channels=True, manage_roles=True)
    channels[30] = category

    async def create_text_channel(name, **kwargs):
        value = channel(40)
        value.overwrites = kwargs["overwrites"]
        return value

    guild.create_text_channel = AsyncMock(side_effect=create_text_channel)
    interaction = SimpleNamespace(
        guild=guild,
        guild_id=1,
        user=creator,
        channel=current,
        channel_id=10,
        message=SimpleNamespace(id=200),
        client=SimpleNamespace(user=bot),
    )
    return SimpleNamespace(
        guild=guild,
        creator=creator,
        staff=staff,
        outsider=outsider,
        admin=admin,
        staff_role=staff_role,
        current=current,
        panel=panel,
        category=category,
        interaction=interaction,
        channels=channels,
    )


@pytest.mark.parametrize(
    "identity,staff_only,allowed",
    [
        ("creator", False, True),
        ("creator", True, False),
        ("staff", True, True),
        ("admin", True, True),
        ("outsider", False, False),
    ],
)
def test_ticket_access_requires_authority_and_source_visibility(identity, staff_only, allowed):
    env = destination()
    env.interaction.user = getattr(env, identity)
    if allowed:
        service.require_access(env.interaction, ticket(), staff_only=staff_only)
    else:
        with pytest.raises(store.TicketError):
            service.require_access(env.interaction, ticket(), staff_only=staff_only)
    env.current.permissions_for.return_value = discord.Permissions.none()
    env.current.permissions_for.side_effect = None
    with pytest.raises(store.TicketError, match="accès"):
        service.require_access(env.interaction, ticket())


def test_private_overwrites_ignore_category_and_archive_restores_all_access():
    async def scenario():
        env = destination()
        original = env.current.overwrites
        assert set(original) == {env.guild.default_role, env.guild.me, env.creator, env.staff_role}
        assert original[env.guild.default_role].view_channel is False
        closed = service.archive_overwrites(env.guild, original)
        assert closed[env.creator].view_channel
        assert closed[env.creator].send_messages is False
        assert closed[env.staff_role].send_messages_in_threads is False
        assert closed[env.guild.me].send_messages is True
        assert original[env.creator].send_messages is True
        restored = await service.deserialize_overwrites(env.guild, service.serialize_overwrites(original))
        assert service.serialize_overwrites(restored) == service.serialize_overwrites(original)

    asyncio.run(scenario())


def test_transcript_includes_metadata_unicode_actions_replies_and_attachment_links():
    async def scenario():
        env = destination()
        env.current.messages = [
            SimpleNamespace(
                id=100,
                author=SimpleNamespace(id=2),
                created_at=datetime(2026, 11, 10, tzinfo=timezone.utc),
                reference=SimpleNamespace(message_id=90),
                content="Bonjour @everyone 🥇",
                attachments=[SimpleNamespace(filename="preuve.png", url="https://example.test/file")],
                embeds=[discord.Embed(title="Preuve", description="Détails en français")],
                stickers=[],
            )
        ]
        session = SimpleNamespace(
            history=AsyncMock(
                return_value=(
                    [{"user_id": 3}],
                    [{"actor_id": 3, "created_at": datetime(2026, 11, 10), "action": "closed", "detail": "Résolu"}],
                )
            )
        )
        content = await service.build_transcript(env.current, ticket(status="closed", close_reason="Résolu"), session)
        text = content.decode("utf-8")
        for expected in (
            "Signalement",
            "Résolu",
            "Personnel intervenu : 3",
            "Bonjour @everyone 🥇",
            "preuve.png",
            "https://example.test/file",
            "réponse à 90",
            "Détails en français",
        ):
            assert expected in text
        env.current.messages *= 2
        service_limit = service.MAX_TRANSCRIPT_MESSAGES
        try:
            service.MAX_TRANSCRIPT_MESSAGES = 1
            with pytest.raises(store.TicketError, match="20 000"):
                await service.build_transcript(env.current, ticket(), session)
        finally:
            service.MAX_TRANSCRIPT_MESSAGES = service_limit
        env.guild.filesize_limit = 65540
        with pytest.raises(store.TicketError, match="taille"):
            await service.build_transcript(env.current, ticket(), session)

    asyncio.run(scenario())


def install_session(monkeypatch, session, *, fail_commit=False):
    @asynccontextmanager
    async def context(guild_id):
        assert guild_id == 1
        yield session
        if fail_commit:
            raise RuntimeError("Commit failed")

    monkeypatch.setattr(service, "ticket_session", context)


def test_creation_rolls_back_discord_channel_if_database_insert_fails(monkeypatch):
    async def scenario():
        env = destination()
        env.interaction.channel, env.interaction.channel_id = env.panel, env.panel.id
        session = SimpleNamespace(
            panel=AsyncMock(
                return_value={
                    "channel_id": 20,
                    "message_id": 200,
                    "category_id": 30,
                    "staff_role_id": 5,
                    "logs_channel_id": None,
                }
            ),
            active=AsyncMock(return_value=None),
            create=AsyncMock(side_effect=RuntimeError("DB failed")),
        )
        install_session(monkeypatch, session)
        with pytest.raises(RuntimeError, match="DB failed"):
            await service.TicketService().create(env.interaction, "report")
        assert 40 not in env.channels

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["transcript", "commit"])
def test_failed_closure_restores_permissions(monkeypatch, failure):
    async def scenario():
        env = destination()
        original = service.serialize_overwrites(env.current.overwrites)
        current = ticket()

        async def close(value, actor_id, reason, overwrites):
            nonlocal current
            current = replace(value, status="closed", closed_by=actor_id, close_reason=reason)

        session = SimpleNamespace(
            get=AsyncMock(side_effect=lambda channel_id: current),
            close=AsyncMock(side_effect=close),
            event=AsyncMock(),
            history=AsyncMock(return_value=([], [])),
            save_transcript=AsyncMock(),
        )
        install_session(monkeypatch, session, fail_commit=failure == "commit")
        if failure == "transcript":
            monkeypatch.setattr(service, "build_transcript", AsyncMock(side_effect=store.TicketError("Export failed")))
        with pytest.raises((store.TicketError, RuntimeError)):
            await service.TicketService().mutate(env.interaction, "closed", reason="Résolu")
        assert service.serialize_overwrites(env.current.overwrites) == original
        assert env.current.edit.await_count == 2

    asyncio.run(scenario())


def test_duplicate_open_and_stale_panel_do_not_create_channels(monkeypatch):
    async def scenario():
        env = destination()
        env.interaction.channel, env.interaction.channel_id = env.panel, 20
        panel = {"channel_id": 20, "message_id": 200}
        session = SimpleNamespace(panel=AsyncMock(return_value=panel), active=AsyncMock(return_value=ticket()))
        install_session(monkeypatch, session)
        with pytest.raises(store.TicketError, match="déjà"):
            await service.TicketService().create(env.interaction, "report")
        panel["message_id"] = 201
        with pytest.raises(store.TicketError, match="plus actif"):
            await service.TicketService().create(env.interaction, "report")
        env.guild.create_text_channel.assert_not_awaited()

    asyncio.run(scenario())


def test_registered_ticket_group_is_public_but_setup_checks_admin_and_view_persists():
    async def scenario():
        async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
            await command.register(bot)
            group = bot.tree.get_command("ticket")
            assert group.default_permissions is None
            assert {item.name for item in group.commands} == {
                "panel",
                "add",
                "remove",
                "rename",
                "close",
                "reopen",
                "transcript",
                "link",
                "info",
                "reconcile",
            }
            for name in ("panel", "reconcile"):
                check = group.get_command(name).checks[0]
                assert not check(SimpleNamespace(user=SimpleNamespace(guild_permissions=discord.Permissions.none())))
                assert check(
                    SimpleNamespace(user=SimpleNamespace(guild_permissions=discord.Permissions(manage_guild=True)))
                )
            view = bot.persistent_views[0]
            assert view.is_persistent()
            assert [item.label for item in view.children[0].options] == list(store.CATEGORIES.values())
            assert group.to_dict(bot.tree)["dm_permission"] is False

    asyncio.run(scenario())


def test_private_logs_cannot_become_public_or_ping_users():
    async def scenario():
        env = destination()
        env.current.permissions_for.side_effect = None
        env.current.permissions_for.return_value = discord.Permissions.all()
        result = await service.TicketService().log_close(env.guild, ticket(logs_channel_id=10), b"private transcript")
        assert "impossible" in result
        env.current.send.assert_not_awaited()

    asyncio.run(scenario())


def test_member_management_reopen_and_subject_link_preserve_access(monkeypatch):
    async def scenario():
        env = destination()
        env.interaction.user = env.staff
        current = ticket()
        session = SimpleNamespace(
            get=AsyncMock(side_effect=lambda channel_id: current),
            event=AsyncMock(),
            link=AsyncMock(),
            reopen=AsyncMock(),
            active=AsyncMock(return_value=None),
        )
        install_session(monkeypatch, session)
        manager = service.TicketService()
        await manager.mutate(env.interaction, "added", user=env.outsider)
        assert env.current.overwrites[env.outsider].view_channel is True
        await manager.mutate(env.interaction, "removed", user=env.outsider)
        assert env.current.overwrites[env.outsider].view_channel is False
        with pytest.raises(store.TicketError, match="automatiquement"):
            await manager.mutate(env.interaction, "removed", user=env.creator)
        before = service.serialize_overwrites(env.current.overwrites)
        await manager.mutate(env.interaction, "linked", user=env.outsider)
        assert before == service.serialize_overwrites(env.current.overwrites)
        session.link.assert_awaited_once_with(current, env.outsider.id)
        await manager.mutate(env.interaction, "renamed", name="Équipe support")
        assert env.current.name == "équipe-support"
        current = replace(current, status="closed", saved_overwrites=json.dumps(before))
        env.current.overwrites = service.archive_overwrites(env.guild, env.current.overwrites)
        session.active.return_value = ticket(id=2)
        with pytest.raises(store.TicketError, match="déjà"):
            await manager.mutate(env.interaction, "reopened")
        session.active.return_value = None
        await manager.mutate(env.interaction, "reopened")
        assert service.serialize_overwrites(env.current.overwrites) == before
        session.reopen.assert_awaited_once()

    asyncio.run(scenario())


def test_mysql_ticket_lifecycle_concurrency_and_transcript_persistence(monkeypatch):
    """Use only an explicitly supplied disposable DB, never production settings."""
    import json
    import os

    import aiomysql

    from src.core.db_init import init_db

    port = os.getenv("TICKET_TEST_DB_PORT") or os.getenv("REMINDER_TEST_DB_PORT")
    if not port:
        pytest.skip("Requires a disposable MySQL test database")

    async def connect():
        return await aiomysql.connect(
            host="127.0.0.1",
            port=int(port),
            user="root",
            password="",
            db="reminder_test",
            autocommit=True,
            charset="utf8mb4",
        )

    monkeypatch.setattr(store, "get_db_connection", connect)

    async def scenario():
        db = await connect()
        try:
            await init_db(db)
            await init_db(db)
            async with db.cursor() as cursor:
                await cursor.execute("DELETE FROM tickets")
                await cursor.execute("DELETE FROM ticket_panels")
        finally:
            db.close()
        env = destination()
        manager = service.TicketService()
        async with store.ticket_session(1) as session:
            await session.save_panel(20, 200, 30, 5, None)
            with pytest.raises(store.TicketError, match="en cours"):
                async with store.ticket_session(1):
                    pytest.fail("The second connection acquired the guild lock")
            async with store.ticket_session(999) as other:
                assert await other.panel() is None

        env.interaction.channel, env.interaction.channel_id = env.panel, 20
        opened = await manager.create(env.interaction, "report")
        assert opened.status == "open" and opened.creator_id == 2
        async with store.ticket_session(999) as other:
            assert await other.get(opened.channel_id) is None
            assert await other.active(2) is None
        with pytest.raises(store.TicketError, match="déjà"):
            await manager.create(env.interaction, "shop")
        env.interaction.channel, env.interaction.channel_id = env.channels[40], 40
        await store.record_staff_message(1, 40, env.outsider)
        await store.record_staff_message(1, 40, env.staff)
        await store.record_staff_message(1, 40, env.staff)
        async with store.ticket_session(1) as session:
            staff, _events = await session.history(opened)
            assert [row["user_id"] for row in staff] == [3]
        env.interaction.user = env.staff
        await manager.mutate(env.interaction, "added", user=env.outsider)
        await manager.mutate(env.interaction, "removed", user=env.outsider)
        await manager.mutate(env.interaction, "renamed", name="rapport-rp")
        await manager.mutate(env.interaction, "linked", user=env.outsider)
        original = service.serialize_overwrites(env.interaction.channel.overwrites)
        env.interaction.user = env.creator
        closed, exported = await manager.mutate(env.interaction, "closed", reason="Problème résolu 🥇")
        assert closed.status == "closed" and closed.closed_by == 2 and closed.closed_at
        assert "Problème résolu 🥇" in exported.decode()
        assert closed.subject_id == env.outsider.id
        assert env.interaction.channel.overwrites[env.creator].send_messages is False
        # A new service instance reads the closing snapshot from persisted data.
        retrieved, content = await service.TicketService().transcript(env.interaction)
        assert retrieved.id == closed.id and content == exported
        env.interaction.user = env.staff
        reopened, _content = await manager.mutate(env.interaction, "reopened")
        assert reopened.status == "open" and reopened.closed_by is None
        assert service.serialize_overwrites(env.interaction.channel.overwrites) == original
        async with store.ticket_session(1) as session:
            _staff, events = await session.history(reopened)
            assert [row["action"] for row in events] == [
                "created",
                "added",
                "removed",
                "renamed",
                "linked",
                "closed",
                "transcript",
                "reopened",
            ]
            assert json.loads(closed.saved_overwrites) == original
            large = ("Échange avec le personnel 🥇\n" * 20000).encode()
            await session.save_transcript(reopened, 3, large)
            assert await session.latest_transcript(reopened) == large
        # The database itself rejects a duplicate, including outside the service.
        with pytest.raises(aiomysql.IntegrityError):
            async with store.ticket_session(1) as session:
                panel = await session.panel()
                await session.create(41, 2, "general", panel)
        # Rollback releases the named lock and preserves the original record.
        async with store.ticket_session(1) as session:
            assert (await session.active(2)).id == reopened.id
            assert await session.get(41) is None
            audits = await session.rows("SELECT action FROM admin_audit WHERE guild_id = 1 AND action LIKE 'ticket.%'")
            assert any(f"#{opened.id}" in row["action"] for row in audits)

    asyncio.run(scenario())


def test_panel_updates_existing_message_and_rejects_invalid_setup(monkeypatch):
    async def scenario():
        env = destination()
        session = SimpleNamespace(
            panel=AsyncMock(return_value={"channel_id": 20, "message_id": 200}),
            save_panel=AsyncMock(),
            execute=AsyncMock(),
        )
        install_session(monkeypatch, session)
        message = SimpleNamespace(id=200, author=env.guild.me, edit=AsyncMock())
        env.panel.fetch_message = AsyncMock(return_value=message)
        result = await service.TicketService().panel(
            env.interaction, env.panel, env.category, env.staff_role, None, None
        )
        assert result.id == 200
        env.panel.send.assert_not_awaited()
        assert message.edit.await_args.kwargs["embed"].title == "Besoin d’aide ?"
        session.save_panel.assert_awaited_once_with(20, 200, 30, 5, None)
        env.staff_role.is_default.return_value = True
        with pytest.raises(store.TicketError, match="dédié"):
            await service.TicketService().panel(env.interaction, env.panel, env.category, env.staff_role, None, None)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "identity,subject_visible,moderation_visible",
    [
        ("creator", False, False),
        ("staff", True, False),
        ("admin", True, True),
    ],
)
def test_info_respects_existing_moderation_permissions(monkeypatch, identity, subject_visible, moderation_visible):
    async def scenario():
        env = destination()
        env.interaction.user = getattr(env, identity)
        env.interaction.response = SimpleNamespace(defer=AsyncMock())
        env.interaction.followup = SimpleNamespace(send=AsyncMock())
        session = SimpleNamespace(
            get=AsyncMock(return_value=ticket(subject_id=4)),
            history=AsyncMock(return_value=([], [])),
            rows=AsyncMock(return_value=[{"total": 2}]),
        )
        install_session(monkeypatch, session)
        monkeypatch.setattr(command, "ticket_session", service.ticket_session)
        group = command.Tickets(service.TicketService())
        await group.get_command("info").callback(group, env.interaction)
        kwargs = env.interaction.followup.send.await_args.kwargs
        fields = {field.name: field.value for field in kwargs["embed"].fields}
        assert ("Utilisateur concerné" in fields) is subject_visible
        assert ("Modération" in fields) is moderation_visible
        assert kwargs["ephemeral"] and kwargs["allowed_mentions"].to_dict()["parse"] == []

    asyncio.run(scenario())
