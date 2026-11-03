import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from discord.ext import commands

from src.events import message_logs as handler
from src.utils.message_logs import MessageSnapshot, UNAVAILABLE, build_bulk_log, build_message_log


GUILD_ID = 123
CHANNEL_ID = 456
MESSAGE_ID = 1300000000000000000


def message(content="Original text", *, author_id=42, attachments=(), message_id=MESSAGE_ID):
    return SimpleNamespace(
        id=message_id, content=content,
        author=SimpleNamespace(id=author_id), attachments=attachments,
    )


def fields(embed):
    return {field.name: field.value for field in embed.fields}


def setup_listeners(monkeypatch):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    bot._connection.user = SimpleNamespace(id=99)
    channel = SimpleNamespace(id=789, send=AsyncMock())
    lookup = AsyncMock(return_value=channel)
    monkeypatch.setattr(handler, "GUILD_IDS", {GUILD_ID})
    monkeypatch.setattr(handler, "get_logs_channel", lookup)
    asyncio.run(handler.register(bot))
    listeners = {name: callbacks[0] for name, callbacks in bot.extra_events.items()}
    return channel, lookup, listeners


def deletion(cached_message=None, *, guild_id=GUILD_ID):
    payload = discord.RawMessageDeleteEvent({
        "guild_id": str(guild_id), "channel_id": str(CHANNEL_ID), "id": str(MESSAGE_ID),
    })
    payload.cached_message = cached_message
    return payload


def update(data, cached_message=None):
    updated_message = SimpleNamespace(
        id=MESSAGE_ID, channel=SimpleNamespace(id=CHANNEL_ID), guild=SimpleNamespace(id=GUILD_ID),
    )
    payload = discord.RawMessageUpdateEvent({
        "guild_id": str(GUILD_ID), "channel_id": str(CHANNEL_ID), "id": str(MESSAGE_ID), **data,
    }, updated_message)
    payload.cached_message = cached_message
    return payload


def test_cached_deletion_has_content_author_identifiers_and_no_pings(monkeypatch):
    channel, lookup, listeners = setup_listeners(monkeypatch)
    asyncio.run(listeners["on_raw_message_delete"](deletion(message("Deleted @everyone <@42>"))))
    assert lookup.await_count == 1
    assert lookup.await_args.args[1] == GUILD_ID
    kwargs = channel.send.await_args.kwargs
    embed = kwargs["embed"]
    assert embed.title == "🗑️ Message supprimé"
    values = fields(embed)
    assert values["Contenu supprimé"] == "Deleted @everyone <@42>"
    assert "42" in values["Auteur du message"]
    assert str(CHANNEL_ID) in values["Salon"]
    assert values["Identifiant du message"] == str(MESSAGE_ID)
    assert "Message envoyé le" in values
    assert embed.timestamp is not None
    assert kwargs["allowed_mentions"].to_dict() == {"parse": []}


def test_uncached_deletion_is_reported_without_inventing_content(monkeypatch):
    channel, _lookup, listeners = setup_listeners(monkeypatch)
    asyncio.run(listeners["on_raw_message_delete"](deletion()))
    values = fields(channel.send.await_args.kwargs["embed"])
    assert values["Contenu supprimé"] == UNAVAILABLE
    assert "Auteur inconnu" in values["Auteur du message"]


def test_edit_uses_event_content_and_includes_before_after_and_link(monkeypatch):
    channel, _lookup, listeners = setup_listeners(monkeypatch)
    asyncio.run(listeners["on_raw_message_edit"](update({"content": "New text"}, message())))
    embed = channel.send.await_args.kwargs["embed"]
    assert embed.title == "✏️ Message modifié"
    assert fields(embed)["Avant"] == "Original text"
    assert fields(embed)["Après"] == "New text"
    assert f"/{GUILD_ID}/{CHANNEL_ID}/{MESSAGE_ID}" in embed.description


def test_uncached_edit_uses_raw_author_and_marks_before_unavailable(monkeypatch):
    channel, _lookup, listeners = setup_listeners(monkeypatch)
    asyncio.run(listeners["on_raw_message_edit"](update({
        "content": "New text", "author": {"id": "42", "username": "Alice"},
    })))
    values = fields(channel.send.await_args.kwargs["embed"])
    assert values["Avant"] == UNAVAILABLE
    assert values["Après"] == "New text"
    assert values["Auteur du message"] == "Alice · <@42> (`42`)"


def test_attachment_only_edit_and_removal_keep_available_text(monkeypatch):
    channel, _lookup, listeners = setup_listeners(monkeypatch)
    attachment = SimpleNamespace(id=8, filename="image.png", url="https://cdn.discordapp.com/image.png")
    asyncio.run(listeners["on_raw_message_edit"](update({"attachments": []}, message(attachments=[attachment]))))
    values = fields(channel.send.await_args.kwargs["embed"])
    assert values["Avant"] == values["Après"] == "Original text"
    assert attachment.url in values["Pièces jointes avant"]
    assert values["Pièces jointes après"] == "Aucune"


@pytest.mark.parametrize("data", [{"embeds": [{}]}, {"pinned": True}, {"content": "Original text"}])
def test_non_content_updates_are_ignored(monkeypatch, data):
    channel, lookup, listeners = setup_listeners(monkeypatch)
    asyncio.run(listeners["on_raw_message_edit"](update(data, message())))
    lookup.assert_not_awaited()
    channel.send.assert_not_awaited()


@pytest.mark.parametrize("guild_id", [None, 999])
def test_private_and_disallowed_guild_events_are_ignored(monkeypatch, guild_id):
    channel, lookup, listeners = setup_listeners(monkeypatch)
    payload = SimpleNamespace(guild_id=guild_id)
    for listener in listeners.values():
        asyncio.run(listener(payload))
    lookup.assert_not_awaited()
    channel.send.assert_not_awaited()


def test_own_messages_do_not_create_recursive_logs(monkeypatch):
    channel, lookup, listeners = setup_listeners(monkeypatch)
    asyncio.run(listeners["on_raw_message_delete"](deletion(message(author_id=99))))
    asyncio.run(listeners["on_raw_message_edit"](update({"content": "New text"}, message(author_id=99))))
    asyncio.run(listeners["on_raw_message_edit"](update({"content": "New text", "author": {"id": "99"}})))
    lookup.assert_not_awaited()
    channel.send.assert_not_awaited()


def test_unconfigured_channel_does_not_send(monkeypatch):
    channel, lookup, listeners = setup_listeners(monkeypatch)
    lookup.return_value = None
    asyncio.run(listeners["on_raw_message_delete"](deletion(message())))
    channel.send.assert_not_awaited()


def test_long_unicode_content_and_attachments_are_preserved_in_file():
    content = "é😀 *_`" * 600
    attachments = tuple((index, "image.png", "https://cdn.discordapp.com/" + "a" * 400) for index in range(10))
    before = MessageSnapshot(42, "Alice", content, attachments)
    after = MessageSnapshot(42, "Alice", "Updated " + content, ())
    embed, file = build_message_log(GUILD_ID, CHANNEL_ID, MESSAGE_ID, before, after)
    try:
        assert len(embed) <= 6000
        assert all(len(field.value) <= 1024 for field in embed.fields)
        transcript = file.fp.read().decode("utf-8")
        assert content in transcript
        assert "Updated " + content in transcript
        assert attachments[-1][2] in transcript
        assert str(MESSAGE_ID) in transcript
    finally:
        file.close()


def test_empty_text_is_distinct_from_unknown_text_and_markdown_is_escaped():
    embed, file = build_message_log(GUILD_ID, CHANNEL_ID, MESSAGE_ID, MessageSnapshot(42, "Alice", "", ()))
    assert fields(embed)["Contenu supprimé"] == "(Aucun contenu textuel)"
    assert file is None
    embed, _file = build_message_log(GUILD_ID, CHANNEL_ID, MESSAGE_ID, MessageSnapshot(42, "Alice", "**text**", ()))
    assert fields(embed)["Contenu supprimé"] == r"\*\*text\*\*"


def test_bulk_deletion_sends_one_summary_with_cached_and_uncached_records(monkeypatch):
    channel, _lookup, listeners = setup_listeners(monkeypatch)
    payload = discord.RawBulkMessageDeleteEvent({
        "guild_id": str(GUILD_ID), "channel_id": str(CHANNEL_ID),
        "ids": [str(MESSAGE_ID + offset) for offset in range(3)],
    })
    payload.cached_messages = [message("Bulk deleted text"), message(author_id=99, message_id=MESSAGE_ID + 1)]
    captured = []

    async def capture(**kwargs):
        captured.append((kwargs["embed"], kwargs["file"].fp.read().decode("utf-8")))

    channel.send.side_effect = capture
    asyncio.run(listeners["on_raw_bulk_message_delete"](payload))
    channel.send.assert_awaited_once()
    embed, transcript = captured[0]
    assert fields(embed)["Messages supprimés"] == "2"
    assert fields(embed)["Contenus en cache"] == "1"
    assert fields(embed)["Messages hors cache"] == "1"
    assert "Bulk deleted text" in transcript
    assert UNAVAILABLE in transcript
    assert str(MESSAGE_ID + 2) in transcript
    assert str(MESSAGE_ID + 1) not in transcript


def test_large_bulk_transcript_respects_embed_limits():
    message_ids = {MESSAGE_ID + offset for offset in range(100)}
    snapshots = {message_id: MessageSnapshot(42, "Alice", "é" * 4000, ()) for message_id in message_ids}
    embed, file = build_bulk_log(GUILD_ID, CHANNEL_ID, message_ids, snapshots)
    try:
        assert len(embed) < 6000
        assert file.fp.read().decode("utf-8").count("é" * 4000) == 100
    finally:
        file.close()


def test_missing_attach_permission_falls_back_to_explicit_summary():
    embed, file = build_message_log(GUILD_ID, CHANNEL_ID, MESSAGE_ID, MessageSnapshot(42, "Alice", "x" * 2000, ()))
    channel = SimpleNamespace(id=789, send=AsyncMock(side_effect=[
        discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions"), None,
    ]))
    asyncio.run(handler.send_log(channel, embed, file))
    assert channel.send.await_count == 2
    assert "file" not in channel.send.await_args.kwargs
    assert "Fichier intégral non envoyé" in embed.description
    assert file.fp.closed


def test_discord_send_failure_is_logged_without_message_content(caplog):
    channel = SimpleNamespace(id=789, send=AsyncMock(side_effect=discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions",
    )))
    embed, file = build_message_log(GUILD_ID, CHANNEL_ID, MESSAGE_ID, MessageSnapshot(42, "Alice", "Private content", ()))
    asyncio.run(handler.send_log(channel, embed, file))
    assert "Message log delivery failed channel=789" in caplog.text
    assert "Private content" not in caplog.text


@pytest.mark.parametrize("row,expected", [(("789",), True), (None, False), (("invalid",), False)])
def test_general_log_configuration_is_guild_scoped_and_connection_closed(monkeypatch, row, expected):
    # Exercise the actual configuration lookup separately from mocked event delivery.
    cursor = AsyncMock()
    cursor.fetchone.return_value = row
    context = AsyncMock()
    context.__aenter__.return_value = cursor
    db = Mock()
    db.cursor.return_value = context
    monkeypatch.setattr(handler, "get_db_connection", AsyncMock(return_value=db))
    bot = Mock()
    channel = bot.get_guild.return_value.get_channel.return_value
    result = asyncio.run(handler.get_logs_channel(bot, GUILD_ID))
    assert result is (channel if expected else None)
    assert cursor.execute.await_args.args[1] == (GUILD_ID,)
    db.close.assert_called_once()
