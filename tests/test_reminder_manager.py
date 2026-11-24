"""Interactive reminder ownership, drafts, confirmations and independent delivery."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import re
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from src.commands.general import remind as command
from src.events import reminder_handler as handler
from src.utils import reminder_actions as actions
from src.utils import reminder_editor as editor
from src.utils import reminder_views as views
from src.utils import reminders as store
from src.utils.reminder_time import PastTimeError, parse_reminder_time
from test_reminder_delivery import reminder, setup_destination


def interaction(user_id=2, guild_id=1):
    bot, guild, owner, _guest, channel = setup_destination()
    state = {"done": False}

    async def done(*args, **kwargs):
        state["done"] = True

    message = SimpleNamespace(edit=AsyncMock())
    return SimpleNamespace(user=owner if user_id == 2 else SimpleNamespace(id=user_id), guild_id=guild_id,
        guild=guild, channel=channel, channel_id=3, client=bot, data={}, extras={},
        response=SimpleNamespace(is_done=lambda: state["done"], defer=AsyncMock(side_effect=done),
            edit_message=AsyncMock(side_effect=done), send_message=AsyncMock(side_effect=done), send_modal=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock(return_value=message)), original_response=AsyncMock(return_value=message),
        edit_original_response=AsyncMock())


@pytest.mark.parametrize("user_id,guild_id,allowed", [(2, 1, True), (3, 1, False), (2, 9, False)])
def test_manager_sessions_are_private_and_bound_to_the_original_member_and_server(user_id, guild_id, allowed):
    async def scenario():
        view = views.ReminderDetails(reminder(personal_number=1))
        inter = interaction(user_id, guild_id)
        assert await view.interaction_check(inter) is allowed
        if not allowed:
            assert inter.response.send_message.await_args.kwargs["ephemeral"]
    asyncio.run(scenario())


def test_dashboard_labels_use_personal_numbers_text_and_dates_without_exposing_global_ids():
    async def scenario():
        records = [reminder(id=9999, personal_number=1, message="Réunion du staff"), reminder(id=8888, personal_number=2)]
        dashboard = views.ReminderDashboard(1, 2, records, {"timezone": "Europe/Brussels", "generation": 0})
        select = next(item for item in dashboard.children if isinstance(item, discord.ui.Select) and item.row == 1)
        assert select.options[0].label == "#1 · Réunion du staff"
        assert "9999" not in str(dashboard.embed().to_dict())
        assert {item.label for item in dashboard.children if isinstance(item, discord.ui.Button)} >= {
            "Créer un rappel", "Réinitialiser mes rappels", "Actualiser"}
        assert len(dashboard.embed()) < 6000
    asyncio.run(scenario())


def test_create_without_parameters_opens_the_assistant_and_keeps_saved_timezone(monkeypatch):
    async def scenario():
        inter = interaction()
        monkeypatch.setattr(command, "get_preferences", AsyncMock(return_value={"timezone": "America/Montreal", "generation": 3}))
        create = AsyncMock()
        monkeypatch.setattr(command, "create_reminder", create)
        group = command.Remind()
        await group.create.callback(group, inter)
        wizard = inter.followup.send.await_args.kwargs["view"]
        assert isinstance(wizard, editor.ReminderEditor)
        assert wizard.draft.timezone == "America/Montreal" and wizard.draft.generation == 3
        assert wizard.step == 0 and inter.followup.send.await_args.kwargs["ephemeral"]
        create.assert_not_awaited()
    asyncio.run(scenario())


def test_full_wizard_uses_native_member_selection_and_saves_only_after_confirmation(monkeypatch):
    async def scenario():
        wizard = editor.ReminderEditor(store.Reminder(1, 2, None, 0, "", generation=4))
        create, validate = AsyncMock(return_value=99), AsyncMock()
        monkeypatch.setattr(editor.store, "create_reminder", create)
        monkeypatch.setattr(editor, "validate_destination", validate)
        saved = reminder(id=99, personal_number=1, message="Réunion", generation=4)
        monkeypatch.setattr(editor.store, "get_owned_reminder", AsyncMock(return_value=saved))
        modal = editor.MessageModal(wizard)
        modal.text._value = "Réunion"
        await modal.on_submit(interaction())
        await wizard.next(interaction())
        inter = interaction()
        inter.data = {"values": ["10m"]}
        await wizard.choose_time(inter)
        await wizard.next(interaction())
        inter = interaction()
        inter.data = {"values": ["3"]}
        await wizard.choose_channel(inter)
        await wizard.next(interaction())
        assert wizard.step == 3
        selector = next(item for item in wizard.children if isinstance(item, discord.ui.UserSelect))
        assert selector.max_values == 10 and selector.min_values == 0
        inter = interaction()
        inter.data = {"values": ["4", "5"]}
        await wizard.choose_members(inter)
        assert wizard.draft.recipient_ids == (4, 5)
        await wizard.toggle_owner(interaction())
        assert not wizard.draft.mention_owner
        await wizard.next(interaction())
        assert wizard.step == 4
        create.assert_not_awaited()
        inter = interaction()
        await wizard.save(inter)
        create.assert_awaited_once()
        assert create.await_args.kwargs == {"expected_generation": 4}
        assert create.await_args.args[0].recipient_ids == (4, 5)
        assert isinstance(inter.edit_original_response.await_args.kwargs["view"], views.ReminderDetails)
        with pytest.raises(ValueError):
            await wizard.save(interaction())
        create.assert_awaited_once()
    asyncio.run(scenario())


def test_switching_draft_to_dm_clears_recipients_and_skips_mentions_step(monkeypatch):
    async def scenario():
        wizard = editor.ReminderEditor(reminder(recipient_ids=(4,)), step=2)
        monkeypatch.setattr(editor, "validate_destination", AsyncMock())
        inter = interaction()
        inter.data = {"values": ["dm"]}
        await wizard.choose_destination(inter)
        assert wizard.draft.recipient_ids == () and wizard.draft.channel_id is None
        await wizard.next(interaction())
        assert wizard.step == 4
        await wizard.back(interaction())
        assert wizard.step == 2
    asyncio.run(scenario())


def test_past_bare_time_requires_an_explicit_choice_of_tomorrow():
    now = datetime(2026, 11, 24, 20, tzinfo=timezone.utc)
    with pytest.raises(PastTimeError) as caught:
        parse_reminder_time("18:00", now=now)
    assert caught.value.tomorrow == "demain 18:00"

    async def scenario():
        wizard = editor.ReminderEditor(reminder(), step=1)
        choice = editor.TomorrowChoice(wizard.draft, "demain 18:00")
        inter = interaction()
        await choice.confirm(inter)
        new_view = inter.response.edit_message.await_args.kwargs["view"]
        assert new_view.draft.due_at > time.time()
        assert new_view.step == 4
    asyncio.run(scenario())


def test_autocomplete_uses_only_owned_mutable_reminders_and_stable_references(monkeypatch):
    async def scenario():
        records = [reminder(id=999, personal_number=1, message="Réunion"), reminder(id=998, personal_number=2, status="sending")]
        listing = AsyncMock(return_value=records)
        monkeypatch.setattr(command, "list_reminders", listing)
        group = command.Remind()
        choices = await group.reminder_choices(interaction(), "réun")
        listing.assert_awaited_once_with(1, 2)
        assert len(choices) == 1 and choices[0].value == "r:999"
        assert choices[0].name.startswith("#1 ·")
        assert group.parse_id("#1") == group.parse_id("1") == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["delete", "reset"])
def test_destructive_confirmations_recheck_revisions_or_generation_and_are_single_use(monkeypatch, kind):
    async def scenario():
        monkeypatch.setattr(views.store, "get_owned_reminder", AsyncMock(return_value=reminder()))
        monkeypatch.setattr(views.ReminderDashboard, "load", AsyncMock(return_value=views.ReminderDashboard(1, 2, [],
            {"timezone": "Europe/Brussels", "generation": 1})))
        delete, reset = AsyncMock(return_value=True), AsyncMock(return_value=1)
        monkeypatch.setattr(views.store, "delete_reminder", delete)
        monkeypatch.setattr(views.store, "reset_reminders", reset)
        view = views.DeleteConfirmation(reminder()) if kind == "delete" else views.ResetConfirmation(1, 2, 0, ((1, 0, "pending"),))
        (delete if kind == "delete" else reset).assert_not_awaited()
        await view.confirm(interaction())
        with pytest.raises(ValueError):
            await view.confirm(interaction())
        if kind == "delete":
            delete.assert_awaited_once_with(1, 1, 2, revision=0)
        else:
            reset.assert_awaited_once_with(1, 2, 0, ((1, 0, "pending"),))
    asyncio.run(scenario())


def test_snooze_received_buttons_only_allow_the_creator_and_survive_reconstruction(monkeypatch):
    async def scenario():
        source = reminder(status="sent")
        lookup = AsyncMock(side_effect=lambda rid, gid, uid, **kwargs: source if uid == 2 else None)
        snooze = AsyncMock(return_value=9)
        monkeypatch.setattr(actions, "get_owned_reminder", lookup)
        monkeypatch.setattr(actions, "snooze_reminder", snooze)
        from src.utils import reminder_delivery
        monkeypatch.setattr(reminder_delivery, "validate_destination", AsyncMock())
        button = actions.SnoozeButton(1, 1, 600)
        match = re.fullmatch(r"aurum:reminders:snooze:(?P<guild>\d+):(?P<reminder>\d+):(?P<delay>600|3600):v1", button.item.custom_id)
        rebuilt = await actions.SnoozeButton.from_custom_id(None, button.item, match)
        await rebuilt.callback(interaction(user_id=3))
        snooze.assert_not_awaited()
        await rebuilt.callback(interaction(guild_id=None))
        snooze.assert_awaited_once()
        assert snooze.await_args.args[1] >= int(time.time()) + 599
    asyncio.run(scenario())


def test_slow_deliveries_do_not_block_other_sends_or_later_polling(monkeypatch):
    async def scenario():
        blocked, second_sent, third_sent = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def deliver(bot, record):
            if record.id == 1:
                await blocked.wait()
            else:
                (second_sent if record.id == 2 else third_sent).set()

        monkeypatch.setattr(handler, "deliver_claimed_reminder", deliver)
        queue = [reminder(id=1), reminder(id=2)]
        monkeypatch.setattr(handler, "claim_next_reminder", AsyncMock(side_effect=lambda *_: queue.pop(0) if queue else None))
        monkeypatch.setattr(handler, "purge_finished_reminders", AsyncMock())
        cog = SimpleNamespace(bot=None, _inflight=set(), _last_cleanup=0)
        cog.deliver_one = lambda record: handler.ReminderDelivery.deliver_one(cog, record)
        try:
            await handler.ReminderDelivery.deliver.coro(cog)
            await asyncio.wait_for(second_sent.wait(), 1)
            await asyncio.sleep(0)
            assert len(cog._inflight) == 1
            queue.append(reminder(id=3))
            await handler.ReminderDelivery.deliver.coro(cog)
            await asyncio.wait_for(third_sent.wait(), 1)
            assert not blocked.is_set()
        finally:
            blocked.set()
            await asyncio.gather(*cog._inflight)
    asyncio.run(scenario())
