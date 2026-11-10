import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.error import HTTPError

import discord
from discord.ext import commands
import pytest

from src.commands.moderation import devlog as command
from src.utils import devlog


BOT_USER = discord.ClientUser(state=None, data={
    "id": "99", "username": "Aurum", "discriminator": "9925", "avatar": None,
})


def release(tag="v1.8.0", title="Add message history"):
    return devlog.Release(tag, title, "https://github.com/Minamix-project/minamix_bot/pull/16")


def github_release(tag="v1.8.0", **changes):
    return {"tag_name": tag, "name": tag, "body": "PR #16 — [MINOR] Add message history", **changes}


@pytest.mark.parametrize("invalid", ["1.8", "v01.8.3", "v1.8.3-beta", "../latest", "v1.8.3\nextra", "1.8.9999999999"])
def test_invalid_versions_cannot_be_used_in_github_paths(invalid):
    with pytest.raises(devlog.DevlogError, match="Version invalide"):
        devlog.Version.parse(invalid)


def test_github_release_notes_produce_clean_pr_titles_and_links():
    entry = devlog.release_entry(github_release("v1.8.3", body="PR #19 — [PATCH] Exclude automated messages"))
    assert entry.tag == "v1.8.3"
    assert entry.title == "Exclude automated messages"
    assert entry.url == "https://github.com/Minamix-project/minamix_bot/pull/19"
    fallback = devlog.release_entry(github_release(body="Manual release notes", name="New features"))
    assert fallback.title == "New features"
    assert fallback.url.endswith("/releases/tag/v1.8.0")


@pytest.mark.parametrize("version", [None, "1.8.3"])
def test_github_discovery_loads_only_the_selected_stable_series(monkeypatch, version):
    responses = [github_release("v1.8.3"), [
        github_release("v1.9.0"), github_release("v1.8.4"), github_release("v1.8.3"),
        github_release("v1.8.2", draft=True), github_release("v1.8.1"), github_release("v1.8.0"),
        github_release("v1.7.9"), github_release("v1.8.4-beta", prerelease=True),
    ]]
    fetch = Mock(side_effect=responses)
    monkeypatch.setattr(devlog, "_request_json", fetch)
    entries = asyncio.run(devlog.fetch_release_group(version))
    assert [entry.tag for entry in entries] == ["v1.8.0", "v1.8.1", "v1.8.3"]
    assert fetch.call_args_list[0].args == ("releases/latest" if version is None else "releases/tags/v1.8.3",)


def test_github_discovery_fails_instead_of_publishing_an_incomplete_series(monkeypatch):
    fetch = Mock(side_effect=[github_release("v1.8.3")] + [[github_release("v1.9.0")] * 100] * 10)
    monkeypatch.setattr(devlog, "_request_json", fetch)
    with pytest.raises(devlog.DevlogError, match="1 000 releases"):
        asyncio.run(devlog.fetch_release_group())
    assert fetch.call_count == 11


def test_catch_up_discovery_includes_all_missing_series_and_patches_across_pages(monkeypatch):
    fetch = Mock(side_effect=[github_release("v1.11.1"), [
        github_release("v1.12.0"), github_release("v1.11.1"), github_release("v1.11.0"),
        *[github_release("v1.11.2-beta", prerelease=True)] * 97,
    ], [
        github_release("v1.10.2"), github_release("v1.10.1", draft=True),
        github_release("v1.10.0"), github_release("v1.9.1"), github_release("v1.9.0"),
    ]])
    monkeypatch.setattr(devlog, "_request_json", fetch)
    entries = asyncio.run(devlog.fetch_release_group("1.11.1", since=devlog.Version.parse("1.9.0")))
    assert [entry.tag for entry in entries] == ["v1.9.1", "v1.10.0", "v1.10.2", "v1.11.0", "v1.11.1"]
    assert fetch.call_args_list[-1].args == ("releases?per_page=100&page=2",)


def test_catch_up_discovery_rejects_a_truncated_release_history(monkeypatch):
    fetch = Mock(side_effect=[github_release("v1.11.0")] + [[github_release("v1.11.0")] * 100] * 10)
    monkeypatch.setattr(devlog, "_request_json", fetch)
    with pytest.raises(devlog.DevlogError, match="1 000 releases"):
        asyncio.run(devlog.fetch_release_group("1.11.0", since=devlog.Version.parse("1.9.0")))


@pytest.mark.parametrize("status,notice", [(404, "Aucune release"), (403, "limite temporairement"), (429, "limite temporairement")])
def test_github_errors_are_actionable(monkeypatch, status, notice):
    monkeypatch.setattr(devlog, "_request_json", Mock(side_effect=HTTPError("url", status, "error", {}, None)))
    with pytest.raises(devlog.DevlogError, match=notice):
        asyncio.run(devlog.fetch_release_group())


def render(entries):
    return devlog.render_pages(entries, BOT_USER.id, major_emoji="<:kchoc:111>", minor_emoji="<:kgun:222>")


def test_format_distinguishes_major_minor_and_patches_and_sorts_numerically():
    pages = render([release("v1.8.10"), release("v1.8.2"), release("v1.8.0")])
    assert pages[0].startswith("<:kgun:222> **Changelog v1.8.0 <@99>** - [Add message history](https://")
    assert pages[0].splitlines()[1].startswith("- **Changelog v1.8.2")
    assert pages[0].splitlines()[2].startswith("- **Changelog v1.8.10")
    assert render([release("v2.0.0"), release("v2.0.1")])[0].startswith("<:kchoc:111>")
    assert devlog.Version.parse("v2.0.0").group == devlog.Version.parse("v2.0.1").group
    assert devlog.Version.parse("v2.1.0").group != devlog.Version.parse("v2.0.0").group


def test_long_series_splits_only_between_complete_entries_within_discord_limits():
    entries = [release(f"v1.8.{index}", "Fix 😀 " * 18) for index in range(20)]
    pages = render(entries)
    assert 1 < len(pages) <= 10
    assert all(len(page.encode("utf-16-le")) // 2 <= 2000 for page in pages)
    assert "\n".join(pages).count("**Changelog") == len(entries)
    with pytest.raises(devlog.DevlogError, match="10 messages"):
        render([release(f"v1.8.{index}", "x" * 300) for index in range(100)])


def test_titles_cannot_break_the_announcement_markdown():
    page = render([release(title="[Feature] Fix **test** @everyone [fake](https://example.com)")])[0]
    assert r"\[Feature\] Fix \*\*test\*\* @everyone \[fake\]\(https://example.com\)" in page
    assert page.endswith(f"]({release().url})")


def fake_destination():
    guild = SimpleNamespace(id=1, me=BOT_USER, emojis=[])
    member = SimpleNamespace(id=42, guild_permissions=discord.Permissions(manage_guild=True))
    bot = SimpleNamespace(user=BOT_USER, emojis=[])
    channel = Mock(spec=discord.TextChannel)
    channel.id, channel.guild, channel.mention = 456, guild, "<#456>"
    channel.permissions_for.return_value = discord.Permissions(
        view_channel=True, send_messages=True, read_message_history=True,
    )
    guild.get_channel = lambda channel_id: channel if channel_id == channel.id else None
    messages = {}
    next_id = 1000

    async def send(content, **kwargs):
        nonlocal next_id
        next_id += 1
        message = SimpleNamespace(id=next_id, content=content, author=BOT_USER)

        async def edit(**options):
            message.content = options["content"]

        async def delete():
            del messages[message.id]

        message.edit, message.delete = AsyncMock(side_effect=edit), AsyncMock(side_effect=delete)
        messages[message.id] = message
        return message

    async def fetch_message(message_id):
        if message_id not in messages:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Missing message")
        return messages[message_id]

    async def history(**kwargs):
        for message in sorted(messages.values(), key=lambda item: item.id, reverse=True)[:kwargs["limit"]]:
            yield message

    channel.send, channel.fetch_message, channel.history = AsyncMock(side_effect=send), AsyncMock(side_effect=fetch_message), history
    return bot, guild, member, channel, messages


def fake_database(monkeypatch, *, row=None, rows=None, configured=True):
    cursor = AsyncMock()
    cursor.fetchone.return_value = ("456",) if configured else None
    if rows is None:
        rows = [(devlog.Release(**json.loads(row[0])[0]).version.group, *row)] if row else []
    cursor.fetchall.return_value = rows
    context = AsyncMock()
    context.__aenter__.return_value = cursor
    db = Mock(begin=AsyncMock(), rollback=AsyncMock(), commit=AsyncMock())
    db.cursor.return_value = context
    monkeypatch.setattr(devlog, "get_db_connection", AsyncMock(return_value=db))
    return db, cursor


def saved_row(cursor):
    values = cursor.execute.await_args.args[1]
    return values[3], values[4]


def stored_batch(group, entries, message_ids):
    return group, json.dumps([devlog.asdict(entry) for entry in entries]), json.dumps(message_ids)


@pytest.mark.parametrize("preview", [False, True])
def test_catch_up_groups_missing_minors_and_patches_in_one_new_message(monkeypatch, preview):
    bot, guild, member, channel, messages = fake_destination()
    entries = [release("v1.10.0"), release("v1.10.1"), release("v1.11.0"), release("v1.11.1")]
    fetch = AsyncMock(return_value=tuple(entries))
    monkeypatch.setattr(devlog, "fetch_release_group", fetch)

    async def scenario():
        previous = await channel.send(render([release("v1.9.0")])[0])
        db, cursor = fake_database(monkeypatch, rows=[stored_batch("1.9", [release("v1.9.0")], [previous.id])])
        result = await devlog.publish_devlog(bot, guild, member, [entries[-1]], preview=preview)
        assert [devlog.ANNOUNCEMENT_PATTERN.findall(page) for page in result.pages] == [[entry.tag for entry in entries]]
        assert result.created == (0 if preview else 1)
        assert result.edited == 0
        previous.edit.assert_not_awaited()
        assert len(messages) == (1 if preview else 2)
        if preview:
            db.rollback.assert_awaited_once()
            db.commit.assert_not_awaited()
            assert cursor.execute.await_count == 2
        else:
            assert cursor.execute.await_args.args[1][2] == "1.10"
        fetch.assert_awaited_once_with("v1.11.1", since=devlog.Version.parse("v1.9.0"))
    asyncio.run(scenario())


def test_catch_up_repairs_an_already_published_latest_minor_and_retries_without_duplicates(monkeypatch):
    bot, guild, member, channel, messages = fake_destination()
    entries = [release("v1.10.0"), release("v1.10.1"), release("v1.11.0")]
    fetch = AsyncMock(return_value=tuple(entries))
    monkeypatch.setattr(devlog, "fetch_release_group", fetch)

    async def scenario():
        previous = await channel.send(render([release("v1.9.0")])[0])
        latest = await channel.send(render([entries[-1]])[0])
        first_row = stored_batch("1.9", [release("v1.9.0")], [previous.id])
        _db, cursor = fake_database(monkeypatch, rows=[first_row, stored_batch("1.11", [entries[-1]], [latest.id])])
        result = await devlog.publish_devlog(bot, guild, member, [entries[-1]])
        assert result.created == 0 and result.edited == 1
        assert result.message_ids == (latest.id,)
        assert devlog.ANNOUNCEMENT_PATTERN.findall(latest.content) == [entry.tag for entry in entries]
        values = cursor.execute.await_args.args[1]
        saved = values[2:5]
        fake_database(monkeypatch, rows=[first_row, saved])
        result = await devlog.publish_devlog(bot, guild, member, [entries[-1]])
        assert result.created == result.edited == 0
        assert len(messages) == 2
        previous.edit.assert_not_awaited()
    asyncio.run(scenario())


def test_patches_update_the_existing_multi_minor_batch_even_for_an_older_minor(monkeypatch):
    bot, guild, member, channel, messages = fake_destination()
    entries = [release("v1.10.0"), release("v1.11.0")]

    async def scenario():
        original = await channel.send(render(entries)[0])
        fake_database(monkeypatch, rows=[stored_batch("1.10", entries, [original.id])])
        result = await devlog.publish_devlog(bot, guild, member, [release("v1.10.1")])
        assert result.created == 0 and result.edited == 1
        assert devlog.ANNOUNCEMENT_PATTERN.findall(original.content) == ["v1.10.0", "v1.10.1", "v1.11.0"]
        assert len(messages) == 1
    asyncio.run(scenario())


def test_catch_up_updates_last_series_patches_separately_from_the_new_batch(monkeypatch):
    bot, guild, member, channel, messages = fake_destination()
    fetch = AsyncMock(return_value=(release("v1.9.1"), release("v1.10.0"), release("v1.11.0")))
    monkeypatch.setattr(devlog, "fetch_release_group", fetch)

    async def scenario():
        previous = await channel.send(render([release("v1.9.0")])[0])
        fake_database(monkeypatch, rows=[stored_batch("1.9", [release("v1.9.0")], [previous.id])])
        result = await devlog.publish_devlog(bot, guild, member, [release("v1.11.0")])
        assert result.created == 1 and result.edited == 1
        assert devlog.ANNOUNCEMENT_PATTERN.findall(previous.content) == ["v1.9.0", "v1.9.1"]
        assert devlog.ANNOUNCEMENT_PATTERN.findall(messages[result.message_ids[-1]].content) == ["v1.10.0", "v1.11.0"]
    asyncio.run(scenario())


def test_catch_up_recovers_a_multi_minor_send_after_database_failure(monkeypatch):
    bot, guild, member, channel, messages = fake_destination()
    entries = (release("v1.10.0"), release("v1.11.0"))
    monkeypatch.setattr(devlog, "fetch_release_group", AsyncMock(return_value=entries))

    async def scenario():
        previous = await channel.send(render([release("v1.9.0")])[0])
        rows = [stored_batch("1.9", [release("v1.9.0")], [previous.id])]
        db, _cursor = fake_database(monkeypatch, rows=rows)
        db.commit.side_effect = RuntimeError("Database unavailable")
        with pytest.raises(RuntimeError):
            await devlog.publish_devlog(bot, guild, member, [entries[-1]])
        fake_database(monkeypatch, rows=rows)
        result = await devlog.publish_devlog(bot, guild, member, [entries[-1]])
        assert result.created == result.edited == 0
        assert len(messages) == channel.send.await_count == 2
    asyncio.run(scenario())


def test_failed_catch_up_discovery_leaves_existing_messages_unchanged(monkeypatch):
    bot, guild, member, channel, messages = fake_destination()
    monkeypatch.setattr(devlog, "fetch_release_group", AsyncMock(side_effect=devlog.DevlogError("GitHub indisponible")))

    async def scenario():
        previous = await channel.send(render([release("v1.9.0")])[0])
        db, _cursor = fake_database(monkeypatch, rows=[stored_batch("1.9", [release("v1.9.0")], [previous.id])])
        with pytest.raises(devlog.DevlogError, match="GitHub indisponible"):
            await devlog.publish_devlog(bot, guild, member, [release("v1.11.0")])
        previous.edit.assert_not_awaited()
        assert len(messages) == channel.send.await_count == 1
        db.rollback.assert_awaited_once()
    asyncio.run(scenario())


def test_preview_is_private_and_does_not_mutate_database_or_discord(monkeypatch):
    bot, guild, member, channel, _messages = fake_destination()
    db, cursor = fake_database(monkeypatch)
    result = asyncio.run(devlog.publish_devlog(bot, guild, member, [release()], preview=True))
    assert result.pages[0].startswith("🎯 **Changelog")
    assert result.message_ids == ()
    channel.send.assert_not_awaited()
    channel.fetch_message.assert_not_awaited()
    assert cursor.execute.await_count == 2
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()
    db.close.assert_called_once()


def test_repeat_publications_edit_existing_posts_and_preserve_newer_patches(monkeypatch):
    bot, guild, member, channel, messages = fake_destination()

    async def scenario():
        _db, cursor = fake_database(monkeypatch)
        first = await devlog.publish_devlog(bot, guild, member, [release()])
        assert first.created == 1
        assert channel.send.await_args.kwargs["allowed_mentions"].to_dict() == {"parse": [], "users": [99]}
        assert channel.send.await_args.kwargs["suppress_embeds"]
        _db, cursor = fake_database(monkeypatch, row=saved_row(cursor))
        repeated = await devlog.publish_devlog(bot, guild, member, [release()])
        assert repeated.created == repeated.edited == 0
        _db, cursor = fake_database(monkeypatch, row=saved_row(cursor))
        patch = await devlog.publish_devlog(bot, guild, member, [release("v1.8.1", "Fix dice")])
        assert patch.created == 0 and patch.edited == 1
        message = next(iter(messages.values()))
        assert message.edit.await_args.kwargs["allowed_mentions"].to_dict() == {"parse": [], "users": [99]}
        assert "<@99>" in message.content
        _db, cursor = fake_database(monkeypatch, row=saved_row(cursor))
        older = await devlog.publish_devlog(bot, guild, member, [release()])
        assert older.created == older.edited == 0
        assert older.message_ids == first.message_ids
        assert len(messages) == channel.send.await_count == 1
        assert "v1.8.1" in next(iter(messages.values())).content
    asyncio.run(scenario())


def test_existing_text_name_is_replaced_with_a_bot_mention_without_a_new_post(monkeypatch):
    bot, guild, member, channel, messages = fake_destination()

    async def scenario():
        original = await channel.send("🎯 **Changelog v1.8.0 @Aurum#9925** - Old announcement")
        fake_database(monkeypatch)
        result = await devlog.publish_devlog(bot, guild, member, [release()])
        assert result.created == 0 and result.edited == 1
        assert result.message_ids == (original.id,)
        assert "**Changelog v1.8.0 <@99>**" in original.content
        assert len(messages) == 1
    asyncio.run(scenario())


def test_retry_recovers_a_send_accepted_before_database_commit_failed(monkeypatch):
    bot, guild, member, channel, messages = fake_destination()

    async def scenario():
        db, _cursor = fake_database(monkeypatch)
        db.commit.side_effect = RuntimeError("Database unavailable")
        with pytest.raises(RuntimeError):
            await devlog.publish_devlog(bot, guild, member, [release()])
        db.rollback.assert_awaited_once()
        db.close.assert_called_once()
        fake_database(monkeypatch)
        result = await devlog.publish_devlog(bot, guild, member, [release()])
        assert result.created == result.edited == 0
        assert len(messages) == channel.send.await_count == 1
    asyncio.run(scenario())


def test_deleted_posts_are_recreated(monkeypatch):
    bot, guild, member, channel, _messages = fake_destination()
    fake_database(monkeypatch, row=(json.dumps([{"tag": "v1.8.0", "title": "Old", "url": release().url}]), "[999]"))
    result = asyncio.run(devlog.publish_devlog(bot, guild, member, [release()]))
    assert result.created == 1
    channel.fetch_message.assert_awaited_once_with(999)


@pytest.mark.parametrize("configured,permissions", [(False, True), (True, False)])
def test_missing_configuration_or_permissions_do_not_post(monkeypatch, configured, permissions):
    bot, guild, member, channel, _messages = fake_destination()
    db, _cursor = fake_database(monkeypatch, configured=configured)
    if not permissions:
        channel.permissions_for.return_value = discord.Permissions.none()
    with pytest.raises(devlog.DevlogError):
        asyncio.run(devlog.publish_devlog(bot, guild, member, [release()]))
    channel.send.assert_not_awaited()
    db.rollback.assert_awaited_once()
    db.close.assert_called_once()


@pytest.mark.parametrize("permissions,allowed", [
    (discord.Permissions.none(), False), (discord.Permissions(manage_messages=True), False),
    (discord.Permissions(manage_guild=True), True), (discord.Permissions(administrator=True), True),
])
def test_both_commands_enforce_admin_access_and_native_visibility(permissions, allowed):
    async def scenario():
        async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
            await command.register(bot)
            interaction = SimpleNamespace(
                guild_id=1, user=SimpleNamespace(id=42, guild_permissions=permissions), created_at=discord.utils.utcnow(),
            )
            for name in ("setdevlog", "devlog"):
                registered = bot.tree.get_command(name)
                assert registered.default_permissions == discord.Permissions(manage_guild=True)
                assert await registered._check_can_run(interaction) is allowed
    asyncio.run(scenario())


@pytest.mark.parametrize("preview", [False, True])
def test_registered_publish_command_reaches_github_storage_and_discord(monkeypatch, preview):
    bot, guild, member, channel, _messages = fake_destination()
    _db, _cursor = fake_database(monkeypatch)
    fetch = AsyncMock(return_value=(release(),))
    monkeypatch.setattr(command, "fetch_release_group", fetch)
    registered = {}

    def tree_command(**kwargs):
        def decorator(callback):
            registered[kwargs["name"]] = callback
            return callback
        return decorator

    bot.tree = SimpleNamespace(command=tree_command)
    interaction = SimpleNamespace(
        guild_id=guild.id, guild=guild, user=member, response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )

    async def scenario():
        await command.register(bot)
        await registered["devlog"](interaction, version="1.8.0", preview=preview)
    asyncio.run(scenario())
    fetch.assert_awaited_once_with("1.8.0")
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    assert channel.send.await_count == (0 if preview else 1)
    assert all(call.kwargs["ephemeral"] for call in interaction.followup.send.await_args_list)


@pytest.mark.skipif(not os.getenv("REMINDER_TEST_DB_PORT"), reason="Requires a disposable MySQL test database")
def test_mysql_devlog_migration_concurrency_and_persistence(monkeypatch):
    import aiomysql
    from src.core.db_init import init_db

    async def connect():
        return await aiomysql.connect(
            host="127.0.0.1", port=int(os.environ["REMINDER_TEST_DB_PORT"]), user="root", password="",
            db="reminder_test", autocommit=True, charset="utf8mb4",
        )

    monkeypatch.setattr(devlog, "get_db_connection", connect)
    monkeypatch.setattr(devlog, "fetch_release_group", AsyncMock(side_effect=lambda version, **kwargs: (release(version),)))
    bot, guild, member, channel, messages = fake_destination()

    async def scenario():
        db = await connect()
        try:
            await init_db(db)
            await init_db(db)
            async with db.cursor() as cursor:
                await cursor.execute("DELETE FROM guild_devlogs")
                await cursor.execute("DELETE FROM guild_config WHERE config_key = 'devlog_channel'")
        finally:
            db.close()
        await devlog.configure_devlog(guild.id, channel.id)
        results = await asyncio.gather(*(devlog.publish_devlog(bot, guild, member, [release()]) for _ in range(2)))
        assert sorted(result.created for result in results) == [0, 1]
        first_id = next(iter(messages))
        result = await devlog.publish_devlog(bot, guild, member, [release("v1.8.1")])
        assert result.created == 0 and result.edited == 1
        assert result.message_ids == (first_id,)
        result = await devlog.publish_devlog(bot, guild, member, [release()])
        assert "v1.8.1" in result.pages[0]
        assert len(messages) == 1
        await devlog.publish_devlog(bot, guild, member, [release("v2.0.0")])
        result = await devlog.publish_devlog(bot, guild, member, [release("v2.0.1")])
        assert result.created == 0 and result.edited == 1
        assert len(messages) == 2
        assert result.pages[0].startswith("🚀 **Changelog v2.0.0")
        assert "v2.0.1" in result.pages[0]
        await devlog.publish_devlog(bot, guild, member, [release("v2.1.0")])
        assert len(messages) == 3
        catch_up = (release("v2.2.0"), release("v2.2.1"), release("v2.3.0"))
        monkeypatch.setattr(devlog, "fetch_release_group", AsyncMock(return_value=catch_up))
        result = await devlog.publish_devlog(bot, guild, member, [catch_up[-1]])
        assert result.created == 1 and len(messages) == 4
        batch_id = result.message_ids[0]
        assert devlog.ANNOUNCEMENT_PATTERN.findall(messages[batch_id].content) == [entry.tag for entry in catch_up]
        monkeypatch.setattr(devlog, "fetch_release_group", AsyncMock(return_value=(release("v2.3.0"), release("v2.3.1"))))
        result = await devlog.publish_devlog(bot, guild, member, [release("v2.3.1")])
        assert result.created == 0 and result.edited == 1
        assert result.message_ids == (batch_id,)
        assert "v2.2.1" in messages[batch_id].content
        assert "v2.3.1" in messages[batch_id].content
        db = await connect()
        try:
            async with db.cursor() as cursor:
                await cursor.execute("SELECT release_group, message_ids FROM guild_devlogs WHERE guild_id = 1 ORDER BY release_group")
                rows = await cursor.fetchall()
                assert [row[0] for row in rows] == ["1.8", "2.0", "2.1", "2.2"]
                assert json.loads(rows[0][1]) == [first_id]
                await cursor.execute("SELECT COUNT(*) FROM guild_devlogs WHERE guild_id = 2")
                assert (await cursor.fetchone())[0] == 0
                await cursor.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = '0012_guild_devlogs'")
                assert (await cursor.fetchone())[0] == 1
        finally:
            db.close()
    asyncio.run(scenario())
