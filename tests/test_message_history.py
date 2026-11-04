import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from cryptography.fernet import Fernet, InvalidToken
import discord
import pytest

from src.commands.moderation import messagehistory as command
from src.events import message_history as worker
from src.events import message_logs as logs
from src.utils import message_history as storage
from src.utils.message_history import HistoryCipher, HistoryEntry, HistoryPolicy, HistoryResult, HistoryStore, load_key
from src.utils.message_logs import MessageSnapshot


def snapshot(content="Private réunion 🎲", *, attachments=()):
    return MessageSnapshot(42, "Alice", content, attachments, automated=False)


def metadata(**changes):
    return dict(guild_id=1, channel_id=2, message_id=3, author_id=42, event_kind="created",
                recorded_at=2_000_000_000, retention_started_at=2_000_000_000, expires_at=2_002_592_000, **changes)


def test_cipher_roundtrip_hides_content_names_and_attachment_urls():
    cipher = HistoryCipher(Fernet.generate_key())
    original = snapshot(attachments=((8, "private.png", "https://cdn.discordapp.com/private.png"),))
    row = metadata()
    row["payload"] = cipher.encrypt(original, row)
    assert cipher.decrypt(row) == original
    for value in (original.content, original.author_name, original.attachments[0][2]):
        assert value.encode() not in row["payload"]
    with pytest.raises(InvalidToken):
        HistoryCipher(Fernet.generate_key()).decrypt(row)


def test_origin_survives_encryption_restart_and_partial_edits():
    key = Fernet.generate_key()
    row = metadata()
    row["payload"] = HistoryCipher(key).encrypt(snapshot(), row)
    restored = HistoryCipher(key).decrypt(row)
    assert restored.is_human
    assert MessageSnapshot.from_update({"content": "Changed"}, restored).is_human
    assert MessageSnapshot.from_update({"content": "Changed", "webhook_id": "1234"}, restored).automated


def test_legacy_encrypted_snapshots_remain_readable_with_unknown_origin():
    cipher = HistoryCipher(Fernet.generate_key())
    row = metadata()
    payload = json.loads(cipher._fernet.decrypt(cipher.encrypt(snapshot(), row)))
    payload["snapshot"].pop("automated")
    row["payload"] = cipher._fernet.encrypt(json.dumps(payload).encode("utf-8"))
    restored = cipher.decrypt(row)
    assert restored.content == snapshot().content
    assert restored.automated is None
    assert not restored.is_human


@pytest.mark.parametrize("kind", ["created", "imported", "edited", "deleted"])
def test_known_automated_messages_never_open_a_database_connection(monkeypatch, kind):
    connect = AsyncMock()
    monkeypatch.setattr(storage, "get_db_connection", connect)
    store = HistoryStore(HistoryCipher(Fernet.generate_key()))
    result = asyncio.run(store.record(1, 2, 3, kind, replace(snapshot(), automated=True)))
    assert not result.recorded
    connect.assert_not_awaited()


@pytest.mark.parametrize("previous", [None, True])
def test_unclassified_events_do_not_store_unknown_or_automated_history(monkeypatch, previous):
    store = HistoryStore(HistoryCipher(Fernet.generate_key()))
    row = None
    if previous is not None:
        row = dict(id=1, **metadata())
        row["payload"] = store.cipher.encrypt(replace(snapshot(), automated=previous), row)
    cursor = AsyncMock()
    cursor.fetchone.return_value = row
    context = AsyncMock()
    context.__aenter__.return_value = cursor
    db = Mock(begin=AsyncMock(), rollback=AsyncMock(), commit=AsyncMock())
    db.cursor.return_value = context
    monkeypatch.setattr(storage, "get_db_connection", AsyncMock(return_value=db))
    monkeypatch.setattr(store, "_policy", AsyncMock(return_value=HistoryPolicy(configured=True)))
    result = asyncio.run(store.record(1, 2, 3, "edited", update={"content": "Changed"}))
    assert not result.recorded
    cursor.executemany.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()
    db.close.assert_called_once()


@pytest.mark.parametrize("field,value", [("guild_id", 9), ("channel_id", 9), ("message_id", 9), ("author_id", 9),
                                       ("event_kind", "deleted"), ("recorded_at", 9), ("expires_at", 9)])
def test_cipher_rejects_metadata_swapping(field, value):
    cipher = HistoryCipher(Fernet.generate_key())
    row = metadata()
    row["payload"] = cipher.encrypt(snapshot(), row)
    row[field] = value
    with pytest.raises(InvalidToken):
        cipher.decrypt(row)


def test_oversized_snapshot_is_rejected_before_storage():
    with pytest.raises(ValueError, match="storage size limit"):
        HistoryCipher(Fernet.generate_key()).encrypt(snapshot("x" * 70000), metadata())


def test_key_file_survives_restart_with_private_permissions(tmp_path):
    path = tmp_path / "keys" / "content.key"
    first = load_key(path, existing_history=False)
    assert first == load_key(path, existing_history=True)
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    with pytest.raises(RuntimeError, match="owner-only"):
        load_key(path, existing_history=True)


def test_missing_key_is_never_replaced_when_history_exists(tmp_path):
    path = tmp_path / "content.key"
    with pytest.raises(RuntimeError, match="original key"):
        load_key(path, existing_history=True)
    assert not path.exists()


def test_key_symlink_is_rejected(tmp_path):
    original = tmp_path / "original.key"
    load_key(original, existing_history=False)
    link = tmp_path / "content.key"
    link.symlink_to(original)
    with pytest.raises(OSError):
        load_key(link, existing_history=True)


def test_concurrent_initializers_share_one_complete_key(tmp_path):
    path = tmp_path / "keys" / "content.key"
    with ThreadPoolExecutor(max_workers=8) as executor:
        keys = list(executor.map(lambda _: load_key(path, existing_history=False), range(16)))
    assert len(set(keys)) == 1
    assert list(path.parent.iterdir()) == [path]


def admin_setup(monkeypatch, *, allowed=True):
    monkeypatch.setattr(command, "GUILD_IDS", {1})
    member = Mock(spec=discord.Member)
    member.id = 42
    member.guild_permissions = discord.Permissions(manage_guild=True)
    guild = Mock(spec=discord.Guild)
    guild.id = 1
    channel = Mock(spec=discord.TextChannel)
    channel.id, channel.guild = 2, guild
    permissions = discord.Permissions(view_channel=allowed, read_message_history=allowed)
    channel.permissions_for.return_value = permissions
    guild.get_channel_or_thread.return_value = channel
    interaction = SimpleNamespace(
        guild_id=1, guild=guild, user=member, permissions=discord.Permissions(manage_guild=True),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()), channel_id=2,
        client=SimpleNamespace(user=SimpleNamespace(id=99, display_avatar=SimpleNamespace(url="https://example.com/bot.png"))),
    )
    return interaction, channel


def test_source_channel_permissions_are_required_before_access(monkeypatch):
    interaction, channel = admin_setup(monkeypatch)
    assert asyncio.run(command.source_channel(interaction, channel.id)) is channel
    channel.permissions_for.return_value = discord.Permissions.none()
    with pytest.raises(discord.app_commands.CheckFailure):
        asyncio.run(command.source_channel(interaction, channel.id))
    interaction.guild_id = 999
    with pytest.raises(discord.app_commands.CheckFailure):
        asyncio.run(command.source_channel(interaction, channel.id))


@pytest.mark.parametrize("permissions", [discord.Permissions(manage_guild=True), discord.Permissions(administrator=True)])
def test_admin_permissions_allow_history_without_manage_messages(monkeypatch, permissions):
    interaction, channel = admin_setup(monkeypatch)
    interaction.user.guild_permissions = permissions
    interaction.permissions = permissions
    channel.permissions_for.return_value = discord.Permissions(view_channel=True, read_message_history=True)
    group = command.MessageHistoryCommands()
    assert group.default_permissions.manage_guild
    assert not group.default_permissions.manage_messages
    assert asyncio.run(group.interaction_check(interaction))
    assert asyncio.run(command.source_channel(interaction, channel.id)) is channel
    # Fixing command visibility must not grant access to hidden source channels.
    channel.permissions_for.return_value = discord.Permissions.none()
    with pytest.raises(discord.app_commands.CheckFailure):
        asyncio.run(command.source_channel(interaction, channel.id))


@pytest.mark.parametrize("command_name", ["recent", "view", "status", "configure", "purge", "import"])
def test_manage_messages_alone_cannot_execute_any_history_command(monkeypatch, command_name):
    interaction, channel = admin_setup(monkeypatch)
    interaction.user.guild_permissions = discord.Permissions(manage_messages=True)
    interaction.permissions = discord.Permissions(manage_messages=True)
    group = command.MessageHistoryCommands()
    with pytest.raises(discord.app_commands.CheckFailure):
        asyncio.run(group.get_command(command_name)._check_can_run(interaction))
    with pytest.raises(discord.app_commands.CheckFailure):
        asyncio.run(command.source_channel(interaction, channel.id))
    interaction.guild.get_channel_or_thread.assert_not_called()


def test_history_navigation_rejects_an_admin_demoted_to_manage_messages(monkeypatch):
    interaction, channel = admin_setup(monkeypatch)
    store = SimpleNamespace(records=AsyncMock())

    async def scenario():
        view = command.HistoryView(interaction, store, channel.id)
        interaction.user.guild_permissions = discord.Permissions(manage_messages=True)
        interaction.permissions = discord.Permissions(manage_messages=True)
        assert not await view.interaction_check(interaction)
        store.records.assert_not_awaited()
    asyncio.run(scenario())


def test_private_thread_membership_is_checked(monkeypatch):
    interaction, _channel = admin_setup(monkeypatch)
    thread = Mock(spec=discord.Thread)
    thread.guild, thread.id = interaction.guild, 2
    thread.is_private.return_value = True
    thread.permissions_for.return_value = discord.Permissions(view_channel=True, read_message_history=True, manage_messages=True)
    thread.fetch_member = AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Member"))
    interaction.guild.get_channel_or_thread.return_value = thread
    with pytest.raises(discord.app_commands.CheckFailure):
        asyncio.run(command.source_channel(interaction, 2))
    thread.permissions_for.return_value.manage_threads = True
    assert asyncio.run(command.source_channel(interaction, 2)) is thread


def test_view_rechecks_permissions_on_navigation_and_does_not_load_hidden_content(monkeypatch):
    interaction, _channel = admin_setup(monkeypatch, allowed=False)
    store = SimpleNamespace(records=AsyncMock())

    async def scenario():
        view = command.HistoryView(interaction, store, 2)
        assert not await view.interaction_check(interaction)
        store.records.assert_not_awaited()
    asyncio.run(scenario())


def test_view_loads_pages_fresh_and_expired_versions_are_not_exported(monkeypatch):
    interaction, _channel = admin_setup(monkeypatch)
    entry = HistoryEntry(1, 1, 2, 3, 42, "edited", 2_000_000_000, 2_000_000_000, 2_002_592_000, snapshot())
    store = SimpleNamespace(records=AsyncMock(side_effect=[[entry], [], []]))

    async def scenario():
        view = command.HistoryView(interaction, store, 2, message_id=3, event_kind=None)
        first = await view.render()
        assert "Private" in str(first.to_dict())
        second = await view.render()
        assert "Private" not in str(second.to_dict())
        await view.export.callback(interaction)
        assert "file" not in interaction.followup.send.await_args.kwargs
        assert interaction.followup.send.await_args.kwargs["ephemeral"]
    asyncio.run(scenario())


def test_recent_menu_opens_versions_without_copying_message_ids(monkeypatch):
    interaction, _channel = admin_setup(monkeypatch)
    interaction.edit_original_response = AsyncMock()
    entry = HistoryEntry(1, 1, 2, 3, 42, "edited", 2_000_000_000, 2_000_000_000, 2_002_592_000, snapshot())
    store = SimpleNamespace(records=AsyncMock(return_value=[entry]))

    async def scenario():
        view = command.HistoryView(interaction, store, 2)
        await view.render()
        assert view.choose.options[0].value == "3"
        assert not view.choose.disabled
        view.choose._values = ["3"]
        await view.choose.callback(interaction)
        assert store.records.await_args.kwargs["message_id"] == 3
        assert view.size == 1
        assert not view.export.disabled
        await view.back.callback(interaction)
        assert store.records.await_args.kwargs["event_kind"] == "changes"
        assert view.size == 5
    asyncio.run(scenario())


def test_destructive_commands_require_explicit_confirmation(monkeypatch):
    interaction, channel = admin_setup(monkeypatch)
    store = Mock()
    monkeypatch.setattr(command, "history_cog", lambda _interaction: SimpleNamespace(store=store))
    group = command.MessageHistoryCommands()
    asyncio.run(group.configure.callback(group, interaction, enabled=False))
    asyncio.run(group.purge.callback(group, interaction, channel))
    assert not store.mock_calls


def test_live_capture_skips_private_guilds_and_own_messages(monkeypatch):
    monkeypatch.setattr(worker, "GUILD_IDS", {1})

    async def scenario():
        bot = Mock()
        bot.user.id = 99
        ready = asyncio.Event()
        bot.wait_until_ready = ready.wait
        store = SimpleNamespace(record=AsyncMock())
        cog = worker.MessageHistory(bot, store)
        try:
            await cog.capture(SimpleNamespace(guild=None))
            await cog.capture(SimpleNamespace(guild=SimpleNamespace(id=999)))
            await cog.capture(SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(id=99)))
            store.record.assert_not_awaited()
        finally:
            await cog.cog_unload()
            assert not cog.maintain.is_running()
    asyncio.run(scenario())


@pytest.mark.parametrize("origin", [
    {"bot": False}, {"bot": True}, {"bot": False, "webhook_id": 1234},
    {"bot": False, "application_id": 5678},
])
def test_live_capture_only_retains_human_messages(monkeypatch, origin):
    monkeypatch.setattr(worker, "GUILD_IDS", {1})

    async def scenario():
        bot = Mock()
        bot.user.id = 99
        bot.wait_until_ready = asyncio.Event().wait
        store = SimpleNamespace(record=AsyncMock())
        cog = worker.MessageHistory(bot, store)
        message = SimpleNamespace(
            id=3, guild=SimpleNamespace(id=1), channel=SimpleNamespace(id=2), content="Text", attachments=[],
            author=SimpleNamespace(id=42, bot=origin["bot"]), webhook_id=origin.get("webhook_id"),
            application_id=origin.get("application_id"),
        )
        try:
            await cog.capture(message)
            if origin == {"bot": False}:
                store.record.assert_awaited_once()
                assert store.record.await_args.args[4].is_human
            else:
                store.record.assert_not_awaited()
        finally:
            await cog.cog_unload()
    asyncio.run(scenario())


def test_import_skips_automated_messages_and_keeps_the_scan_limit(monkeypatch):
    interaction, channel = admin_setup(monkeypatch)
    store = SimpleNamespace(
        policy=AsyncMock(return_value=HistoryPolicy(configured=True)),
        record=AsyncMock(return_value=HistoryResult(snapshot(), recorded=True)),
    )
    cog = SimpleNamespace(store=store, importing_guilds=set())
    monkeypatch.setattr(command, "history_cog", lambda _interaction: cog)
    audit = AsyncMock()
    monkeypatch.setattr(command, "record_admin_action", audit)

    async def history(**kwargs):
        assert kwargs["limit"] == 5
        for message_id, origin in enumerate([
            {"bot": True}, {"webhook_id": 1234}, {"application_id": 5678}, {}, {"bot": True},
        ], start=100):
            yield SimpleNamespace(
                id=message_id, author=SimpleNamespace(id=42, bot=origin.get("bot", False)), content="Text",
                attachments=[], webhook_id=origin.get("webhook_id"), application_id=origin.get("application_id"),
                created_at=discord.utils.utcnow(),
            )

    channel.history = history
    group = command.MessageHistoryCommands()
    asyncio.run(group.import_messages.callback(group, interaction, channel, limit=5))
    store.record.assert_awaited_once()
    assert store.record.await_args.args[2] == 103
    assert store.record.await_args.args[4].is_human
    assert "5 message(s) parcouru(s), 1 ajouté(s)" in interaction.followup.send.await_args.args[0]
    assert not cog.importing_guilds
    assert "scanned=5, imported=1" in audit.await_args.args[3]


def test_cleanup_covers_guilds_removed_from_allowlist(monkeypatch):
    monkeypatch.setattr(worker, "GUILD_IDS", {1})
    store = SimpleNamespace(known_guilds=AsyncMock(return_value={1, 999}), cleanup=AsyncMock())
    bot = Mock()
    bot.get_guild.side_effect = lambda guild_id: object() if guild_id == 1 else None
    asyncio.run(worker.MessageHistory.maintain.coro(SimpleNamespace(store=store, bot=bot)))
    calls = {call.args[0]: call.kwargs["active"] for call in store.cleanup.await_args_list}
    assert calls == {1: True, 999: False}


@pytest.mark.parametrize("event", ["edited", "deleted", "bulk"])
@pytest.mark.parametrize("automated", [False, True, None])
def test_uncached_logs_only_include_persisted_human_messages(monkeypatch, event, automated):
    monkeypatch.setattr(logs, "GUILD_IDS", {1})
    channel = SimpleNamespace(send=AsyncMock())
    lookup = AsyncMock(return_value=channel)
    monkeypatch.setattr(logs, "get_logs_channel", lookup)
    saved = replace(snapshot("Persisted before restart"), automated=automated)
    after = replace(snapshot("Updated after restart"), automated=automated) if event == "edited" else None
    result = HistoryResult(saved, after, True)
    bot = Mock()
    bot.user.id = 99
    bot.user.display_avatar.url = "https://example.com/bot.png"
    bot.get_cog.return_value.store.record = AsyncMock(return_value=result)
    callbacks = {}

    def listen(name):
        def register(callback):
            callbacks[name] = callback
            return callback
        return register

    bot.listen = listen
    asyncio.run(logs.register(bot))
    payload = SimpleNamespace(guild_id=1, channel_id=2, message_id=3, cached_message=None,
                              data={"content": "Updated after restart"}, cached_messages=[], message_ids={3})
    callback = {"edited": "on_raw_message_edit", "deleted": "on_raw_message_delete", "bulk": "on_raw_bulk_message_delete"}[event]
    asyncio.run(callbacks[callback](payload))
    if automated is not False:
        channel.send.assert_not_awaited()
        lookup.assert_not_awaited()
        return
    channel.send.assert_awaited_once()
    values = {item.name: item.value for item in channel.send.await_args.kwargs["embed"].fields}
    if event == "edited":
        assert values["Avant"] == "Persisted before restart"
        assert values["Après"] == "Updated after restart"
    elif event == "deleted":
        assert values["Contenu supprimé"] == "Persisted before restart"
    else:
        assert values["Messages supprimés"] == "1"
        assert values["Contenus disponibles"] == "1"


def test_storage_failures_do_not_expose_private_data_in_console(monkeypatch, caplog):
    bot = Mock()
    bot.get_cog.return_value.store.record = AsyncMock(side_effect=ValueError("Private database detail"))
    result = asyncio.run(logs.resolve_history(bot, 1, 2, 3, "deleted", snapshot()))
    assert result.before == snapshot()
    assert "ValueError" in caplog.text
    assert "Private database detail" not in caplog.text


@pytest.mark.skipif(not os.getenv("REMINDER_TEST_DB_PORT"), reason="Requires a disposable MySQL test database")
def test_mysql_encrypted_history_lifecycle_limits_and_concurrency(monkeypatch):
    import aiomysql
    from src.core.db_init import init_db

    async def connect():
        return await aiomysql.connect(
            host="127.0.0.1", port=int(os.environ["REMINDER_TEST_DB_PORT"]), user="root", password="",
            db="reminder_test", autocommit=True, charset="utf8mb4",
        )

    monkeypatch.setattr(storage, "get_db_connection", connect)
    key = Fernet.generate_key()
    store = HistoryStore(HistoryCipher(key))

    async def scenario():
        db = await connect()
        try:
            await init_db(db)
            await init_db(db)
            async with db.cursor() as cursor:
                await cursor.execute("DELETE FROM guild_message_history")
                await cursor.execute("DELETE FROM guild_message_history_state")
                for guild_id in (1, 2):
                    await cursor.execute(
                        "INSERT INTO guild_config (guild_id, config_key, value) VALUES (%s, 'logs_channel', '789') "
                        "ON DUPLICATE KEY UPDATE value = '789'", (guild_id,),
                    )
        finally:
            db.close()

        now = int(time.time())
        assert (await store.record(1, 2, 3, "created", snapshot())).recorded
        assert not (await store.record(999, 2, 3, "created", snapshot())).recorded
        db = await connect()
        try:
            async with db.cursor() as cursor:
                await cursor.execute("SELECT payload FROM guild_message_history WHERE guild_id = 1")
                payload = (await cursor.fetchone())[0]
                assert snapshot().content.encode("utf-8") not in payload
                assert b"Alice" not in payload
        finally:
            db.close()

        restarted = HistoryStore(HistoryCipher(key))
        monkeypatch.setenv("MESSAGE_HISTORY_KEY", key.decode("ascii"))
        initialized = await storage.initialize_history_store()
        assert (await initialized.records(1, 2, message_id=3))[0].snapshot == snapshot()
        monkeypatch.setenv("MESSAGE_HISTORY_KEY", Fernet.generate_key().decode("ascii"))
        with pytest.raises(RuntimeError, match="does not match"):
            await storage.initialize_history_store()
        monkeypatch.setenv("MESSAGE_HISTORY_KEY", key.decode("ascii"))
        assert (await restarted.records(1, 2, message_id=3))[0].snapshot == snapshot()
        assert await restarted.records(2, 2, message_id=3) == []
        assert await restarted.records(1, 999, message_id=3) == []
        result = await restarted.record(1, 2, 3, "edited", update={"content": "Updated"})
        assert result.before == snapshot()
        assert result.after.content == "Updated"
        assert not (await restarted.record(1, 2, 3, "imported", snapshot("Stale imported content"), source_created_at=now)).recorded
        assert (await restarted.records(1, 2, message_id=3))[0].snapshot.content == "Updated"
        deleted = await restarted.record(1, 2, 3, "deleted")
        assert deleted.before.content == "Updated"
        assert not (await restarted.record(1, 2, 3, "created", snapshot("Delayed create"))).recorded
        assert (await restarted.records(1, 2, message_id=3))[0].event_kind == "deleted"

        # Imported data cannot outlive the retention window of its original creation.
        assert not (await store.record(1, 2, 4, "imported", snapshot(), source_created_at=now - 31 * 86400)).recorded
        assert (await store.record(1, 2, 4, "imported", snapshot(), source_created_at=now - 10 * 86400)).recorded
        assert (await store.records(1, 2, message_id=4))[0].expires_at <= now + 20 * 86400
        await store.configure(1, retention_days=7)
        assert await store.records(1, 2, message_id=4) == []

        # Repeated edits and concurrent messages stay inside both hard limits.
        await store.record(1, 2, 5, "created", snapshot())
        for index in range(15):
            await store.record(1, 2, 5, "edited", update={"content": f"Version {index}"})
        versions = await store.records(1, 2, message_id=5, limit=10)
        assert len(versions) == storage.MAX_VERSIONS
        assert versions[0].snapshot.content == "Version 14"
        await store.record(1, 2, 6, "created", snapshot())
        await asyncio.gather(*(store.record(
            1, 2, 6, "edited", snapshot() if index == 0 else snapshot(f"Concurrent version {index - 1}"),
            update={"content": f"Concurrent version {index}"},
        ) for index in range(6)))
        assert (await store.records(1, 2, message_id=6))[0].snapshot.content == "Concurrent version 5"
        await store.configure(1, max_entries=100)
        for start in range(100, 230, 10):
            await asyncio.gather(*((store if number % 2 else restarted).record(1, 2, number, "created", snapshot())
                                   for number in range(start, start + 10)))
        assert (await store.policy(1)).entry_count == 100
        db = await connect()
        try:
            async with db.cursor() as cursor:
                await cursor.execute("SELECT COUNT(*) FROM guild_message_history WHERE guild_id = 1")
                assert (await cursor.fetchone())[0] == 100
        finally:
            db.close()

        # Purging invalidates an already-running import, without affecting other guilds.
        await store.record(2, 2, 7, "created", snapshot("Other guild"))
        generation = (await store.policy(1)).generation
        assert await store.purge(1, 2) == 100
        assert not (await store.record(1, 2, 999, "imported", snapshot(), expected_generation=generation)).recorded
        assert (await store.policy(1)).entry_count == 0
        assert (await store.records(2, 2))[0].snapshot.content == "Other guild"

        # Expired content is hidden immediately, before the cleanup worker runs.
        await store.record(1, 2, 8, "created", snapshot("Expired"), now=now - 8 * 86400)
        assert await store.records(1, 2, message_id=8) == []
        await store.cleanup(1)
        assert (await store.policy(1)).entry_count == 0
        await store.record(1, 2, 9, "created", snapshot())
        await store.configure(1, enabled=False)
        assert (await store.policy(1)).entry_count == 0
        assert not (await store.record(1, 2, 10, "created", snapshot())).recorded
        assert await store.records(1, 2) == []
        await store.cleanup(2, active=False)
        assert (await store.policy(2)).entry_count == 0
    asyncio.run(scenario())
