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
        1, 1, 10, 2, "report", (5,), None, None, "open", datetime(2026, 11, 10), None, None, None, None, 2
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
        value.display_name = f"Member {user_id}"
        value.display_avatar = SimpleNamespace(url=f"https://example.test/avatar-{user_id}.png")
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
    bot.name = "Aurum"
    bot.display_avatar = SimpleNamespace(url="https://example.test/avatar.png")
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
        value.overwrites = service.private_overwrites(guild, creator, [staff_role])

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
        value.name = name
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


@pytest.mark.parametrize("creator_has_support_role", [False, True])
def test_private_overwrites_ignore_category_and_archive_restores_all_access(creator_has_support_role):
    async def scenario():
        env = destination()
        if creator_has_support_role:
            env.creator.roles.append(env.staff_role)
        original = env.current.overwrites
        assert set(original) == {env.guild.default_role, env.guild.me, env.creator, env.staff_role}
        assert original[env.guild.default_role].view_channel is False
        original[env.outsider] = service.member_overwrite()
        original[env.staff] = service.member_overwrite()
        closed = service.archive_overwrites(env.guild, original, (5,), creator_id=env.creator.id)
        assert closed[env.creator].view_channel is False
        assert closed[env.outsider].view_channel is False
        assert closed[env.staff_role].view_channel is True
        assert closed[env.staff].view_channel is True
        assert closed[env.guild.me].view_channel is True
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
            panel_for_message=AsyncMock(
                return_value={
                    "channel_id": 20,
                    "message_id": 200,
                    "category_id": 30,
                    "staff_role_ids": (5,),
                    "transcript_channel_id": None,
                }
            ),
            active=AsyncMock(return_value=None),
            next_number=AsyncMock(return_value=1),
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
        env.current.overwrites[env.outsider] = service.member_overwrite()
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
        session = SimpleNamespace(
            panel_for_message=AsyncMock(return_value=panel), active=AsyncMock(return_value=ticket())
        )
        install_session(monkeypatch, session)
        with pytest.raises(store.TicketError, match="déjà"):
            await service.TicketService().create(env.interaction, "report")
        session.panel_for_message.return_value = None
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
                "purge",
            }
            for name in ("panel", "reconcile", "purge"):
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
        result = await service.TicketService().send_transcript(
            env.guild, ticket(transcript_channel_id=10), b"private transcript"
        )
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
        with pytest.raises(store.TicketError, match="créateur"):
            await manager.mutate(env.interaction, "removed", user=env.creator)
        await manager.mutate(env.interaction, "added", user=env.outsider)
        before = service.serialize_overwrites(env.current.overwrites)
        await manager.mutate(env.interaction, "linked", user=env.outsider)
        assert before == service.serialize_overwrites(env.current.overwrites)
        session.link.assert_awaited_once_with(current, env.outsider.id)
        await manager.mutate(env.interaction, "renamed", name="Équipe support")
        assert env.current.name == "équipe-support"
        current = replace(current, status="closed", saved_overwrites=json.dumps(before))
        env.current.overwrites = service.archive_overwrites(
            env.guild, env.current.overwrites, (5,), creator_id=env.creator.id
        )
        session.active.return_value = ticket(id=2)
        with pytest.raises(store.TicketError, match="déjà"):
            await manager.mutate(env.interaction, "reopened")
        session.active.return_value = None
        await manager.mutate(env.interaction, "reopened")
        assert service.serialize_overwrites(env.current.overwrites) == before
        session.reopen.assert_awaited_once()
        assert env.current.overwrites[env.creator].view_channel is True
        assert env.current.overwrites[env.outsider].view_channel is True

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
                await cursor.execute("DELETE FROM ticket_sequences")
                await cursor.execute("DELETE FROM guild_message_history WHERE guild_id IN (1, 999)")
        finally:
            db.close()
        env = destination()
        manager = service.TicketService()
        async with store.ticket_session(1) as session:
            await session.save_panel(20, 200, 30, (5,), None)
            with pytest.raises(store.TicketError, match="en cours"):
                async with store.ticket_session(1):
                    pytest.fail("The second connection acquired the guild lock")
            async with store.ticket_session(999) as other:
                assert await other.panels() == []

        env.interaction.channel, env.interaction.channel_id = env.panel, 20
        opened = await manager.create(env.interaction, "report")
        assert opened.status == "open" and opened.creator_id == 2
        assert opened.reference == "0001"
        assert env.channels[40].name == "ticket-0001"
        welcome = env.channels[40].send.await_args
        assert welcome.args[0] == "Bienvenue <@2> !"
        assert "L'équipe de support te répondra prochainement." in welcome.kwargs["embed"].description
        assert welcome.kwargs["embed"].footer.text == "Aurum"
        assert welcome.kwargs["embed"].footer.icon_url == "https://example.test/avatar.png"
        assert welcome.kwargs["allowed_mentions"].to_dict()["users"] == [2]
        assert welcome.kwargs["allowed_mentions"].to_dict()["parse"] == []
        assert welcome.kwargs["view"].is_persistent()
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
        await manager.mutate(env.interaction, "added", user=env.outsider)
        await manager.mutate(env.interaction, "renamed", name="rapport-rp")
        await manager.mutate(env.interaction, "linked", user=env.outsider)
        original = service.serialize_overwrites(env.interaction.channel.overwrites)
        env.interaction.user = env.creator
        closed, exported = await manager.mutate(
            env.interaction, "closed", reason="Problème résolu 🥇", creator_only=True, expected_ticket_id=opened.id
        )
        assert closed.status == "closed" and closed.closed_by == 2 and closed.closed_at
        assert "Problème résolu 🥇" in exported.decode()
        assert closed.subject_id == env.outsider.id
        assert env.interaction.channel.overwrites[env.creator].send_messages is False
        assert env.interaction.channel.overwrites[env.creator].view_channel is False
        assert env.interaction.channel.overwrites[env.outsider].view_channel is False
        assert env.interaction.channel.overwrites[env.staff_role].view_channel is True
        # Closed participants cannot consult the ticket; staff can retrieve the persisted snapshot.
        with pytest.raises(store.TicketError, match="accès"):
            await service.TicketService().transcript(env.interaction)
        env.interaction.user = env.staff
        retrieved, content = await service.TicketService().transcript(env.interaction)
        assert retrieved.id == closed.id and content == exported
        reopened, _content = await manager.mutate(env.interaction, "reopened")
        assert reopened.status == "open" and reopened.closed_by is None
        assert service.serialize_overwrites(env.interaction.channel.overwrites) == original
        assert env.interaction.channel.overwrites[env.creator].view_channel is True
        assert env.interaction.channel.overwrites[env.outsider].view_channel is True
        async with store.ticket_session(1) as session:
            _staff, events = await session.history(reopened)
            assert [row["action"] for row in events] == [
                "created",
                "added",
                "removed",
                "added",
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
                panel = (await session.panels())[0]
                await session.create(41, 2, "general", panel)
        # Rollback releases the named lock and preserves the original record.
        async with store.ticket_session(1) as session:
            assert (await session.active(2)).id == reopened.id
            assert await session.get(41) is None
            audits = await session.rows("SELECT action FROM admin_audit WHERE guild_id = 1 AND action LIKE 'ticket.%'")
            assert any(f"#{opened.reference}" in row["action"] for row in audits)

        # Purge all ticket data for one guild while preserving another guild and its counter.
        async with store.ticket_session(999) as other:
            other_panel = {"staff_role_ids": (5,), "transcript_channel_id": None}
            await other.save_panel(90, 900, 91, (5,), None)
            await other.create(92, 2, "general", other_panel)
            foreign = await other.get(92)
            await other.save_transcript(foreign, 3, b"Other guild transcript")
        async with store.ticket_session(1) as session:
            await session.create(41, 7, "general", (await session.panels())[0])
            await session.execute(
                "INSERT INTO guild_message_history_state (guild_id, entry_count) VALUES (1, 2) "
                "ON DUPLICATE KEY UPDATE entry_count = 2"
            )
            for channel_id in (40, 60):
                await session.execute(
                    "INSERT INTO guild_message_history (guild_id, channel_id, message_id, event_kind, recorded_at, "
                    "retention_started_at, expires_at, payload) VALUES (1, %s, %s, 'created', 0, 0, 2000000000, 'test')",
                    (channel_id, channel_id * 100),
                )
        env.interaction.user, env.interaction.channel_id = env.admin, 20

        async def fetch(channel_id):
            if channel_id not in env.channels:
                raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Missing channel")
            return env.channels[channel_id]

        env.guild.fetch_channel = AsyncMock(side_effect=fetch)
        expected = await manager.purge_preview(env.interaction)
        assert len(expected) == 2
        assert await manager.purge(env.interaction, expected) == 2
        assert 40 not in env.channels and 20 in env.channels
        async with store.ticket_session(1) as session:
            assert await session.all() == []
            assert len(await session.panels()) == 1
            for table in ("ticket_staff", "ticket_events", "ticket_transcripts"):
                remaining = await session.rows(
                    f"SELECT COUNT(*) AS total FROM {table} WHERE ticket_id = %s", (opened.id,)
                )
                assert remaining[0]["total"] == 0
            histories = await session.rows("SELECT channel_id FROM guild_message_history WHERE guild_id = 1")
            assert [row["channel_id"] for row in histories] == [60]
            state = await session.rows("SELECT entry_count FROM guild_message_history_state WHERE guild_id = 1")
            assert state[0]["entry_count"] == 1
            audit = await session.rows("SELECT action FROM admin_audit WHERE guild_id = 1 AND action LIKE 'ticket.%'")
            assert [row["action"] for row in audit] == ["ticket.purge: count=2"]
        async with store.ticket_session(999) as other:
            assert (await other.get(92)).id == foreign.id
            assert await other.latest_transcript(foreign) == b"Other guild transcript"
            assert await other.next_number() == 2
        env.interaction.channel = env.panel
        env.interaction.user = env.creator
        restarted = await manager.create(env.interaction, "shop")
        assert restarted.id > opened.id and restarted.reference == "0001"
        assert env.channels[40].name == "ticket-0001"

    asyncio.run(scenario())


def test_panel_updates_existing_message_and_rejects_invalid_setup(monkeypatch):
    async def scenario():
        env = destination()
        env.interaction.user = env.admin
        draft = store.PanelDraft(id=1, staff_role_ids=(5,), category_id=30, channel_id=20, version=1)
        session = SimpleNamespace(
            panel=AsyncMock(return_value={"id": 1, "channel_id": 20, "message_id": 200, "version": 1}),
            save_panel=AsyncMock(return_value=1),
            execute=AsyncMock(),
            get=AsyncMock(return_value=None),
        )
        install_session(monkeypatch, session)
        message = SimpleNamespace(id=200, author=env.guild.me, embeds=[], edit=AsyncMock())
        env.panel.fetch_message = AsyncMock(return_value=message)
        result = await service.TicketService().panel(env.interaction, draft, None)
        assert result.id == 200
        env.panel.send.assert_not_awaited()
        assert message.edit.await_args.kwargs["embed"].title == "Besoin d’aide ?"
        session.save_panel.assert_awaited_once_with(
            20,
            200,
            30,
            (5,),
            None,
            panel_id=1,
            name="Support",
            title=service.DEFAULT_PANEL_TITLE,
            text=service.DEFAULT_PANEL_TEXT,
        )
        env.staff_role.is_default.return_value = True
        with pytest.raises(store.TicketError, match="dédiés"):
            await service.TicketService().panel(env.interaction, draft, None)

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


@pytest.mark.parametrize("rejected", [False, True])
def test_category_menu_resets_before_every_attempt_even_when_rejected(rejected):
    async def scenario():
        manager = SimpleNamespace(create=AsyncMock(return_value=ticket()))
        if rejected:
            manager.create.side_effect = store.TicketError("Ticket déjà ouvert")
        view = command.TicketPanel(manager)
        interaction = SimpleNamespace(
            data={"values": ["report"]},
            response=SimpleNamespace(edit_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        for _attempt in range(2):
            if rejected:
                with pytest.raises(store.TicketError):
                    await view.choose(interaction)
            else:
                await view.choose(interaction)
        assert interaction.response.edit_message.await_count == 2
        assert manager.create.await_count == 2
        for call in interaction.response.edit_message.await_args_list:
            fresh_view = call.kwargs["view"]
            assert fresh_view is not view
            assert all(not option.default for option in fresh_view.children[0].options)
        assert manager.create.await_args.args[1] == "report"

    asyncio.run(scenario())


def test_custom_panel_title_text_and_bot_footer(monkeypatch):
    async def scenario():
        env = destination()
        env.interaction.user = env.admin
        session = SimpleNamespace(
            save_panel=AsyncMock(return_value=1), execute=AsyncMock(), get=AsyncMock(return_value=None)
        )
        install_session(monkeypatch, session)
        env.panel.send.return_value = SimpleNamespace(id=200, delete=AsyncMock())
        draft = store.PanelDraft(
            name="Support",
            title="Support du serveur",
            text=r"Bonjour !\nComment peut-on t'aider ?",
            category_id=30,
            channel_id=20,
            staff_role_ids=(5,),
        )
        await service.TicketService().panel(env.interaction, draft, None)
        embed = env.panel.send.await_args.kwargs["embed"]
        assert embed.title == "Support du serveur"
        assert embed.description == "Bonjour !\nComment peut-on t'aider ?"
        assert embed.footer.text == "Aurum"
        assert embed.footer.icon_url == "https://example.test/avatar.png"
        assert session.save_panel.await_args.kwargs["text"] == embed.description

    asyncio.run(scenario())


def confirmation_interaction(user_id=8, *, admin=True):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, guild_permissions=discord.Permissions(manage_guild=admin)),
        guild_id=1,
        response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


def test_purge_confirmation_cannot_be_reused_or_used_by_another_member():
    async def scenario():
        manager = SimpleNamespace(purge=AsyncMock(return_value=2))
        view = command.TicketPurgeConfirmation(manager, 8, 1, (1, 2))
        stranger = confirmation_interaction(9)
        await view.confirm.callback(stranger)
        manager.purge.assert_not_awaited()
        demoted = confirmation_interaction(admin=False)
        await view.confirm.callback(demoted)
        manager.purge.assert_not_awaited()
        owner = confirmation_interaction()
        await view.confirm.callback(owner)
        await view.confirm.callback(owner)
        manager.purge.assert_awaited_once_with(owner, (1, 2))
        assert view.is_finished()
        assert "ticket-0001" in owner.edit_original_response.await_args.kwargs["content"]
        cancelled = command.TicketPurgeConfirmation(manager, 8, 1, (1, 2))
        await cancelled.cancel.callback(owner)
        await cancelled.confirm.callback(owner)
        assert manager.purge.await_count == 1

    asyncio.run(scenario())


def test_purge_preview_does_not_delete_and_confirmation_is_required():
    async def scenario():
        env = destination()
        env.interaction.user = env.admin
        env.interaction.response = SimpleNamespace(defer=AsyncMock())
        env.interaction.followup = SimpleNamespace(send=AsyncMock())
        manager = SimpleNamespace(purge_preview=AsyncMock(return_value=(1, 2)), purge=AsyncMock())
        group = command.Tickets(manager)
        await group.get_command("purge").callback(group, env.interaction)
        manager.purge.assert_not_awaited()
        assert isinstance(env.interaction.followup.send.await_args.kwargs["view"], command.TicketPurgeConfirmation)
        assert "irréversible" in env.interaction.followup.send.await_args.kwargs["embed"].description

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["permissions", "changed", "panel", "caller"])
def test_purge_preserves_records_and_counter_when_it_cannot_finish(monkeypatch, failure):
    async def scenario():
        env = destination()
        env.interaction.user = env.admin
        env.interaction.channel_id = 50
        session = SimpleNamespace(
            all=AsyncMock(return_value=[ticket()]),
            panels=AsyncMock(return_value=[{"channel_id": 20}]),
            purge=AsyncMock(),
            execute=AsyncMock(),
        )
        env.guild.fetch_channel = AsyncMock(return_value=env.current)
        install_session(monkeypatch, session)
        expected = (1,)
        if failure == "permissions":
            env.current.delete.side_effect = discord.Forbidden(
                SimpleNamespace(status=403, reason="Forbidden"), "denied"
            )
        elif failure == "changed":
            expected = ()
        elif failure == "panel":
            session.panels.return_value[0]["channel_id"] = 10
        else:
            env.interaction.channel_id = 10
        with pytest.raises(store.TicketError):
            await service.TicketService().purge(env.interaction, expected)
        session.purge.assert_not_awaited()
        if failure != "permissions":
            env.guild.fetch_channel.assert_not_awaited()

    asyncio.run(scenario())


def test_existing_default_channel_names_are_padded_but_custom_names_are_preserved(monkeypatch):
    async def scenario():
        env = destination()
        env.current.name = "ticket-1"
        env.panel.name = "rapport-personnalise"
        session = SimpleNamespace(
            all=AsyncMock(return_value=[ticket(ticket_number=1), ticket(id=2, channel_id=20, ticket_number=2)])
        )
        install_session(monkeypatch, session)
        await service.TicketService().normalize_channel_names(env.guild)
        assert env.current.name == "ticket-0001"
        env.panel.edit.assert_not_awaited()

    asyncio.run(scenario())


def test_mysql_upgrade_preserves_existing_numbers_and_backfills_per_guild_sequences(monkeypatch, tmp_path):
    import os
    from pathlib import Path

    import aiomysql

    from src.core.db_init import init_db
    from src.core import schema_migrations

    port = os.getenv("TICKET_TEST_DB_PORT") or os.getenv("REMINDER_TEST_DB_PORT")
    if not port:
        pytest.skip("Requires a disposable MySQL test database")
    current_migrations = Path("src/migrations")
    legacy_migrations = tmp_path / "legacy_migrations"
    legacy_migrations.mkdir()
    for migration in current_migrations.glob("*.sql"):
        if migration.name < "0014":
            (legacy_migrations / migration.name).write_text(migration.read_text())
    monkeypatch.setattr(schema_migrations, "MIGRATIONS_DIR", legacy_migrations)

    async def scenario():
        admin = await aiomysql.connect(host="127.0.0.1", port=int(port), user="root", password="", autocommit=True)
        try:
            async with admin.cursor() as cursor:
                await cursor.execute("CREATE DATABASE ticket_upgrade_test CHARACTER SET utf8mb4")
            db = await aiomysql.connect(
                host="127.0.0.1",
                port=int(port),
                user="root",
                password="",
                db="ticket_upgrade_test",
                autocommit=True,
                charset="utf8mb4",
            )
            try:
                await init_db(db)
                async with db.cursor() as cursor:
                    await cursor.execute(
                        "INSERT INTO tickets (id, guild_id, channel_id, creator_id, category, staff_role_id) "
                        "VALUES (11, 1, 101, 2, 'general', 5), (22, 1, 102, 3, 'report', 5), (42, 2, 201, 2, 'shop', 5)"
                    )
                    await cursor.execute(
                        "INSERT INTO ticket_panels (guild_id, channel_id, message_id, category_id, staff_role_id, logs_channel_id) "
                        "VALUES (1, 20, 200, 30, 5, 60)"
                    )
                    await cursor.execute(
                        "INSERT INTO guild_config (guild_id, config_key, value) VALUES (1, 'logs_channel', '50')"
                    )
                monkeypatch.setattr(schema_migrations, "MIGRATIONS_DIR", current_migrations)
                await init_db(db)
                await init_db(db)
                async with db.cursor() as cursor:
                    await cursor.execute("SELECT id, ticket_number FROM tickets ORDER BY id")
                    assert list(await cursor.fetchall()) == [(11, 11), (22, 22), (42, 42)]
                    await cursor.execute("SELECT guild_id, next_number FROM ticket_sequences ORDER BY guild_id")
                    assert list(await cursor.fetchall()) == [(1, 23), (2, 43)]
                    await cursor.execute(
                        "SELECT id, staff_role_ids, transcript_channel_id, channel_id, message_id FROM ticket_panels WHERE guild_id = 1"
                    )
                    panel = await cursor.fetchone()
                    assert json.loads(panel[1]) == [5] and panel[2:] == (60, 20, 200)
                    await cursor.execute(
                        "SELECT panel_id, staff_role_ids, transcript_channel_id FROM tickets WHERE id = 11"
                    )
                    migrated = await cursor.fetchone()
                    assert migrated[0] == panel[0] and json.loads(migrated[1]) == [5]
                    await cursor.execute(
                        "SELECT value FROM guild_config WHERE guild_id = 1 AND config_key = 'logs_channel'"
                    )
                    assert (await cursor.fetchone())[0] == "50"
            finally:
                db.close()
        finally:
            async with admin.cursor() as cursor:
                await cursor.execute("DROP DATABASE ticket_upgrade_test")
            admin.close()

    asyncio.run(scenario())


def test_multiple_support_roles_grant_access_and_are_preserved_in_private_overwrites():
    env = destination()
    extra_role = Mock(spec=discord.Role)
    extra_role.id, extra_role.guild = 6, env.guild
    env.outsider.roles = [extra_role]
    assert service.is_staff(env.outsider, (5, 6))
    assert not service.is_staff(env.outsider, (5,))
    overwrites = service.private_overwrites(env.guild, env.creator, [env.staff_role, extra_role])
    assert overwrites[env.staff_role].view_channel and overwrites[extra_role].view_channel
    assert overwrites[env.guild.default_role].view_channel is False


def test_stale_panel_editor_is_rejected_before_publishing(monkeypatch):
    async def scenario():
        env = destination()
        env.interaction.user = env.admin
        session = SimpleNamespace(panel=AsyncMock(return_value={"id": 1, "version": 2}))
        install_session(monkeypatch, session)
        draft = store.PanelDraft(id=1, staff_role_ids=(5,), category_id=30, channel_id=20, version=1)
        with pytest.raises(store.TicketError, match="modifié ou supprimé"):
            await service.TicketService().panel(env.interaction, draft, None)
        env.panel.send.assert_not_awaited()
        env.panel.fetch_message.assert_not_called()

    asyncio.run(scenario())


def test_general_action_logs_and_transcript_files_have_separate_destinations(monkeypatch):
    async def scenario():
        env = destination()
        cursor = AsyncMock()
        cursor.fetchone.return_value = ("10",)
        context = AsyncMock()
        context.__aenter__.return_value = cursor
        db = Mock()
        db.cursor.return_value = context
        monkeypatch.setattr(service, "get_db_connection", AsyncMock(return_value=db))
        closed = ticket(transcript_channel_id=20, closed_by=2, close_reason="Résolu")
        manager = service.TicketService()
        await manager.log_action(env.guild, closed, "closed", 2)
        assert "'logs_channel'" in cursor.execute.await_args.args[0]
        assert "file" not in env.current.send.await_args.kwargs
        assert await manager.send_transcript(env.guild, closed, b"private messages") is None
        assert env.panel.send.await_args.kwargs["file"].filename == "ticket-0001.txt"
        assert "private messages" not in str(env.current.send.await_args.kwargs["embed"].to_dict())

    asyncio.run(scenario())


def test_mysql_multiple_panels_remain_independent_and_existing_tickets_keep_their_access(monkeypatch):
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
    monkeypatch.setattr(service, "get_db_connection", connect)

    async def scenario():
        db = await connect()
        try:
            await init_db(db)
            async with db.cursor() as cursor:
                await cursor.execute("DELETE FROM tickets")
                await cursor.execute("DELETE FROM ticket_panels")
        finally:
            db.close()
        async with store.ticket_session(1) as session:
            first_id = await session.save_panel(
                20, 200, 30, (5, 6), 60, name="Support RP", title="RP", text="Explique ton problème."
            )
            second_id = await session.save_panel(20, 201, 31, (7,), 61, name="Boutique")
            first = await session.panel_for_message(20, 200)
            second = await session.panel_for_message(20, 201)
            assert first["id"] == first_id and second["id"] == second_id
            await session.create(40, 2, "rp", first)
            old_ticket = await session.get(40)
            await session.save_panel(21, 210, 32, (8,), 62, panel_id=first_id, name="Support RP modifié")
        # A restart resolves each panel by its own message and retains optimistic edit versions.
        async with store.ticket_session(1) as session:
            assert await session.panel_for_message(20, 200) is None
            assert (await session.panel_for_message(21, 210))["id"] == first_id
            assert (await session.panel_for_message(20, 201))["id"] == second_id
            assert (await session.panel(first_id))["version"] == 2
            retained = await session.get(40)
            assert retained.staff_role_ids == (5, 6) and retained.transcript_channel_id == 60
            assert retained.panel_id == first_id
            assert len(await session.panels()) == 2
        async with store.ticket_session(999) as foreign:
            assert await foreign.panel(first_id) is None
            assert await foreign.panel_for_message(20, 201) is None
            await foreign.delete_panel(second_id)
        async with store.ticket_session(1) as session:
            assert await session.panel(second_id) is not None
            await session.delete_panel(first_id)
            assert len(await session.panels()) == 1
            retained = await session.get(40)
            assert retained.id == old_ticket.id and retained.panel_id is None
            assert retained.staff_role_ids == (5, 6) and retained.transcript_channel_id == 60

    asyncio.run(scenario())
