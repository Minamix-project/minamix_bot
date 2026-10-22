import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from src.events import reminder_handler as handler
from src.utils import reminder_delivery as delivery
from src.utils.reminders import Reminder, validate_reminder


def reminder(**changes):
    return replace(Reminder(1, 2, 3, 2_000_000_000, "Check @everyone <@&9> <@99>", id=1), **changes)


def setup_destination():
    guild = Mock(spec=discord.Guild)
    guild.id = 1
    owner = Mock(spec=discord.Member)
    owner.id, owner.guild, owner.display_name = 2, guild, "Creator"
    owner.send = AsyncMock()
    guest = Mock(spec=discord.Member)
    guest.id, guest.guild = 4, guild
    guild.get_member.side_effect = lambda user_id: {2: owner, 4: guest}.get(user_id)
    guild.fetch_member = AsyncMock(return_value=None)
    channel = Mock(spec=discord.TextChannel)
    channel.id, channel.guild = 3, guild
    channel.permissions_for.return_value = discord.Permissions(view_channel=True, send_messages=True, embed_links=True)
    channel.send = AsyncMock()
    guild.get_channel.return_value = channel
    bot = Mock()
    bot.get_guild.return_value = guild
    return bot, guild, owner, guest, channel


@pytest.mark.parametrize("value,expected", [("<@2> <@!4>,2", (2, 4)), ("aucun", ()), ("none", ()), ("2 4", (2, 4))])
def test_recipient_selection(value, expected):
    assert delivery.parse_recipients(value) == expected


@pytest.mark.parametrize("value", ["@everyone", "<@&123>", "member-name", "", "0", str(2**64),
                                  " ".join(str(number) for number in range(1, 12))])
def test_invalid_recipient_selection(value):
    with pytest.raises(ValueError):
        delivery.parse_recipients(value)


def test_text_validation_and_dm_recipients():
    for text in (" ", "x" * 1001):
        with pytest.raises(ValueError):
            validate_reminder(reminder(message=text))
    with pytest.raises(ValueError, match="envoi dans un salon"):
        validate_reminder(reminder(channel_id=None, recipient_ids=(4,)))


def test_channel_delivery_only_allows_explicit_user_mentions():
    bot, _guild, _owner, _guest, channel = setup_destination()
    asyncio.run(delivery.send_reminder(bot, reminder(recipient_ids=(4,))))
    kwargs = channel.send.await_args.kwargs
    assert kwargs["content"] == "<@2> <@4>"
    assert kwargs["embed"].description == "Check @everyone <@&9> <@99>"
    assert kwargs["embed"].title == "⏰ Rappel personnalisé"
    assert kwargs["embed"].fields[0].name == "Prévu pour le"
    assert kwargs["embed"].footer.text == "Rappel #1 · Créé par Creator"
    mentions = kwargs["allowed_mentions"].to_dict()
    assert mentions["users"] == [2, 4]
    assert mentions["parse"] == []


def test_dm_delivery_and_opt_out_of_owner_mention():
    bot, _guild, owner, _guest, channel = setup_destination()
    asyncio.run(delivery.send_reminder(bot, reminder(channel_id=None, mention_owner=False)))
    channel.send.assert_not_awaited()
    assert owner.send.await_args.kwargs["content"] is None
    assert owner.send.await_args.kwargs["allowed_mentions"].to_dict()["users"] == []


@pytest.mark.parametrize("missing", ["owner", "bot", "recipient"])
def test_permissions_rechecked_at_delivery(missing):
    bot, guild, owner, guest, channel = setup_destination()
    denied = {"owner": owner, "bot": guild.me, "recipient": guest}[missing]
    channel.permissions_for.side_effect = lambda member: (
        discord.Permissions.none() if member is denied else discord.Permissions.all()
    )
    with pytest.raises(ValueError):
        asyncio.run(delivery.send_reminder(bot, reminder(recipient_ids=(4,))))
    channel.send.assert_not_awaited()


def test_removed_owner_prevents_delivery():
    bot, guild, _owner, _guest, channel = setup_destination()
    guild.get_member.return_value = None
    guild.get_member.side_effect = None
    with pytest.raises(ValueError, match="créateur"):
        asyncio.run(delivery.send_reminder(bot, reminder()))
    channel.send.assert_not_awaited()


@pytest.mark.parametrize("error,permanent,attempts", [
    (None, False, 1), (ValueError("No access"), True, 1),
    (TimeoutError(), False, 1), (TimeoutError(), False, 5),
])
def test_delivery_success_permanent_failure_and_retry(monkeypatch, error, permanent, attempts):
    send = AsyncMock(side_effect=error)
    finish, notify, report = AsyncMock(return_value=True), AsyncMock(), AsyncMock()
    monkeypatch.setattr(handler, "send_reminder", send)
    monkeypatch.setattr(handler, "finish_reminder", finish)
    monkeypatch.setattr(handler, "notify_failure", notify)
    monkeypatch.setattr(handler, "report_error", report)
    asyncio.run(handler.deliver_claimed_reminder(Mock(), reminder(attempts=attempts)))
    kwargs = finish.await_args.kwargs
    if error is None:
        assert kwargs == {}
    else:
        assert kwargs.get("permanent", False) == permanent
        assert kwargs["error"]
    assert notify.await_count == int(error is not None and (permanent or attempts == 5))


def test_cancellation_leaves_the_lease_recoverable(monkeypatch):
    monkeypatch.setattr(handler, "send_reminder", AsyncMock(side_effect=asyncio.CancelledError()))
    finish = AsyncMock()
    monkeypatch.setattr(handler, "finish_reminder", finish)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(handler.deliver_claimed_reminder(Mock(), reminder()))
    finish.assert_not_awaited()


def test_creation_defaults_and_edit_to_dm_clear_recipients(monkeypatch):
    from src.commands.general import remind as command

    interaction = SimpleNamespace(
        guild_id=1, user=SimpleNamespace(id=2), client=Mock(),
        response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()),
    )
    validate = AsyncMock()
    create, edit = AsyncMock(return_value=17), AsyncMock(return_value=True)
    monkeypatch.setattr(command, "validate_destination", validate)
    monkeypatch.setattr(command, "create_reminder", create)
    monkeypatch.setattr(command, "edit_reminder", edit)
    monkeypatch.setattr(command, "get_reminder", AsyncMock(return_value=reminder(recipient_ids=(4,))))
    group = command.Remind()
    asyncio.run(group.create.callback(group, interaction, "2h", "Check announcements"))
    assert create.await_args.args[0].channel_id is None
    assert interaction.response.defer.await_args.kwargs == {"ephemeral": True}
    asyncio.run(group.edit.callback(group, interaction, "1", delivery="dm"))
    assert edit.await_args.args[0].channel_id is None
    assert edit.await_args.args[0].recipient_ids == ()


def test_worker_starts_once_and_stops_on_cog_unload():
    async def scenario():
        bot = Mock()
        # Keep the worker waiting for ready, without contacting Discord or MySQL.
        ready = asyncio.Event()
        bot.wait_until_ready = ready.wait
        cog = handler.ReminderDelivery(bot)
        assert cog.deliver.is_running()
        task = cog.deliver.get_task()
        await asyncio.sleep(0)
        await cog.cog_unload()
        assert task.done()
        assert not cog.deliver.is_running()
    asyncio.run(scenario())


def test_interrupted_final_attempt_is_not_sent_again(monkeypatch):
    send, finish, notify = AsyncMock(), AsyncMock(return_value=True), AsyncMock()
    monkeypatch.setattr(handler, "send_reminder", send)
    monkeypatch.setattr(handler, "finish_reminder", finish)
    monkeypatch.setattr(handler, "notify_failure", notify)
    asyncio.run(handler.deliver_claimed_reminder(Mock(), reminder(attempts=6)))
    send.assert_not_awaited()
    assert finish.await_args.kwargs["permanent"]
    notify.assert_awaited_once()


def test_worker_continues_after_one_reminder_cannot_be_finalized(monkeypatch):
    first, second = reminder(id=1), reminder(id=2)
    claim = AsyncMock(side_effect=[first, second, None])
    deliver = AsyncMock(side_effect=[RuntimeError("Database temporarily unavailable"), None])
    cleanup = AsyncMock()
    monkeypatch.setattr(handler, "claim_next_reminder", claim)
    monkeypatch.setattr(handler, "deliver_claimed_reminder", deliver)
    monkeypatch.setattr(handler, "purge_finished_reminders", cleanup)
    cog = SimpleNamespace(bot=Mock(), _last_cleanup=0)
    asyncio.run(handler.ReminderDelivery.deliver.coro(cog))
    assert deliver.await_count == 2
    cleanup.assert_awaited_once()


def test_real_bot_close_unloads_reminder_worker():
    from discord.ext import commands

    async def scenario():
        async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
            await handler.register(bot)
            cog = bot.get_cog("ReminderDelivery")
            task = cog.deliver.get_task()
            await asyncio.sleep(0)
            assert not task.done()
        assert task.done()
        assert not cog.deliver.is_running()
    asyncio.run(scenario())
