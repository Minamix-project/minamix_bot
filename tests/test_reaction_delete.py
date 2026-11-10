"""Reaction deletion authorization and coexistence with RP ownership."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
from discord.ext import commands
import pytest

from src.events import rp_handler
from src.utils import reaction_delete as deletion


def setup(monkeypatch):
    monkeypatch.setattr(deletion, "GUILD_IDS", {1})
    message = SimpleNamespace(delete=AsyncMock())
    guild = SimpleNamespace(id=1, get_member=Mock(return_value=SimpleNamespace(id=deletion.REACTION_DELETE_USER_ID)))
    channel = SimpleNamespace(guild=guild, fetch_message=AsyncMock(return_value=message))
    bot = SimpleNamespace(
        get_guild=Mock(return_value=guild),
        get_channel=Mock(return_value=channel),
        fetch_channel=AsyncMock(return_value=channel),
    )
    payload = SimpleNamespace(
        guild_id=1, channel_id=10, message_id=100, user_id=deletion.REACTION_DELETE_USER_ID, emoji="❌", member=None
    )
    report = AsyncMock()
    monkeypatch.setattr(deletion, "report_error", report)
    return bot, payload, channel, message, report


@pytest.mark.parametrize("rp_owner", [None, deletion.REACTION_DELETE_USER_ID, 42])
def test_selected_user_can_delete_any_message_and_rp_ownership_is_cleaned(monkeypatch, rp_owner):
    async def scenario():
        bot, payload, channel, message, report = setup(monkeypatch)
        tracked = {100: (rp_owner, 0)} if rp_owner is not None else {}
        assert await deletion.handle_delete_reaction(bot, payload, tracked)
        channel.fetch_message.assert_awaited_once_with(100)
        message.delete.assert_awaited_once()
        assert tracked == {}
        report.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["other_user", "other_emoji", "custom_emoji", "dm", "other_guild"])
def test_other_users_and_unrelated_reactions_never_fetch_or_delete_messages(monkeypatch, change):
    async def scenario():
        bot, payload, channel, message, report = setup(monkeypatch)
        if change == "other_user":
            payload.user_id = 42
        elif change == "other_emoji":
            payload.emoji = "❎"
        elif change == "custom_emoji":
            payload.emoji = discord.PartialEmoji(name="x", id=123)
        elif change == "dm":
            payload.guild_id = None
        else:
            payload.guild_id = 999
        assert not await deletion.handle_delete_reaction(bot, payload, {})
        bot.get_channel.assert_not_called()
        channel.fetch_message.assert_not_awaited()
        message.delete.assert_not_awaited()
        report.assert_not_awaited()

    asyncio.run(scenario())


def test_existing_rp_owner_deletion_is_preserved_but_other_rp_owners_are_rejected(monkeypatch):
    async def scenario():
        bot, payload, channel, message, report = setup(monkeypatch)
        payload.user_id = 42
        tracked = {100: (43, 0)}
        assert not await deletion.handle_delete_reaction(bot, payload, tracked)
        channel.fetch_message.assert_not_awaited()
        tracked[100] = (42, 0)
        assert await deletion.handle_delete_reaction(bot, payload, tracked)
        message.delete.assert_awaited_once()
        assert not tracked

    asyncio.run(scenario())


def test_uncached_channel_is_resolved_and_cross_guild_channels_are_rejected(monkeypatch):
    async def scenario():
        bot, payload, channel, message, report = setup(monkeypatch)
        bot.get_channel.return_value = None
        assert await deletion.handle_delete_reaction(bot, payload, {})
        bot.fetch_channel.assert_awaited_once_with(10)
        message.delete.reset_mock()
        channel.guild = SimpleNamespace(id=999)
        assert not await deletion.handle_delete_reaction(bot, payload, {})
        message.delete.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [404, 403, 500])
def test_missing_messages_and_discord_errors_do_not_raise_or_lose_retry_ownership(monkeypatch, status):
    async def scenario():
        bot, payload, channel, message, report = setup(monkeypatch)
        response = SimpleNamespace(status=status, reason="Failure")
        error_type = {404: discord.NotFound, 403: discord.Forbidden, 500: discord.HTTPException}[status]
        message.delete.side_effect = error_type(response, "Failure")
        tracked = {100: (payload.user_id, 0)}
        assert not await deletion.handle_delete_reaction(bot, payload, tracked)
        if status == 404:
            assert tracked == {}
            report.assert_not_awaited()
        else:
            assert 100 in tracked
            report.assert_awaited_once()
            assert report.await_args.kwargs["guild_ids"] == 1
            assert report.await_args.kwargs["source"] == "reaction_delete"

    asyncio.run(scenario())


def test_rp_and_general_deletion_share_a_single_listener(monkeypatch):
    async def scenario():
        async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
            await rp_handler.register(bot)
            assert bot.intents.guild_reactions
            listeners = bot.extra_events["on_raw_reaction_add"]
            assert len(listeners) == 1
            handle = AsyncMock()
            monkeypatch.setattr(rp_handler, "handle_delete_reaction", handle)
            payload = SimpleNamespace()
            await listeners[0](payload)
            handle.assert_awaited_once_with(bot, payload, rp_handler._rp_messages)

    asyncio.run(scenario())
