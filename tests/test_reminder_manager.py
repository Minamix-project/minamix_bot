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


def test_dashboard_labels_use_personal_numbers_and_titles_without_exposing_message_bodies_or_global_ids():
    async def scenario():
        records = [reminder(id=9999, personal_number=1, title="Réunion du staff", message="Détails visibles dans la fiche seulement"),
                   reminder(id=8888, personal_number=2)]
        dashboard = views.ReminderDashboard(1, 2, records, {"timezone": "Europe/Brussels", "generation": 0})
        select = next(item for item in dashboard.children if isinstance(item, discord.ui.Select) and item.row == 1)
        assert select.options[0].label == "#1 · Réunion du staff"
        assert "9999" not in str(dashboard.embed().to_dict())
        assert "Détails visibles" not in str(dashboard.embed().to_dict())
        assert dashboard.embed().fields[0].name == "#1 · Réunion du staff"
        assert {item.label for item in dashboard.children if isinstance(item, discord.ui.Button)} >= {
            "Créer un rappel", "Réinitialiser mes rappels", "Actualiser"}
        assert len(dashboard.embed()) < 6000
    asyncio.run(scenario())


def test_create_button_opens_the_assistant_and_keeps_saved_timezone(monkeypatch):
    async def scenario():
        inter = interaction()
        preferences = {"timezone": "America/Montreal", "generation": 3}
        monkeypatch.setattr(views.store, "get_preferences", AsyncMock(return_value=preferences))
        create = AsyncMock()
        monkeypatch.setattr(views.store, "create_reminder", create)
        dashboard = views.ReminderDashboard(1, 2, [], preferences)
        await dashboard.create(inter)
        wizard = inter.edit_original_response.await_args.kwargs["view"]
        assert isinstance(wizard, editor.ReminderEditor)
        assert wizard.draft.timezone == "America/Montreal" and wizard.draft.generation == 3
        assert wizard.step == 0 and wizard.draft.channel_id is None
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
        modal.title_input._value = "Réunion du staff"
        modal.text._value = "Réunion"
        await modal.on_submit(interaction())
        await wizard.next(interaction())
        inter = interaction()
        inter.data = {"values": ["demain 18:00"]}
        await wizard.choose_time(inter)
        inter = interaction()
        inter.data = {"values": ["30"]}
        await wizard.choose_advance(inter)
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
        assert create.await_args.args[0].title == "Réunion du staff"
        assert create.await_args.args[0].message == "Réunion"
        assert create.await_args.args[0].advance_minutes == 30
        assert isinstance(inter.edit_original_response.await_args.kwargs["view"], views.ReminderDetails)
        with pytest.raises(ValueError):
            await wizard.save(interaction())
        create.assert_awaited_once()
    asyncio.run(scenario())


def test_edit_form_prefills_and_saves_the_title_separately_from_the_message(monkeypatch):
    async def scenario():
        original = reminder(title="Réunion", message="Retrouve le staff à 18 h.")
        wizard = editor.ReminderEditor(original, editing=True)
        modal = editor.MessageModal(wizard)
        assert len(modal.children) == 2
        assert modal.title_input.default == "Réunion" and modal.text.default == original.message
        assert modal.title_input.required and modal.text.required
        modal.title_input._value = "  Réunion   du staff  "
        modal.text._value = original.message
        await modal.on_submit(interaction())
        monkeypatch.setattr(store, "get_owned_reminder", AsyncMock(return_value=original))
        edit = AsyncMock(return_value=True)
        monkeypatch.setattr(store, "edit_reminder", edit)
        await wizard.save(interaction())
        saved = edit.await_args.args[0]
        assert saved.title == "Réunion du staff" and saved.message == original.message
        assert saved.id == original.id and saved.revision == original.revision
    asyncio.run(scenario())


def test_reminder_titles_are_validated_and_unicode_list_labels_fit_discord_limits():
    for title in ("   ", "a" * 81):
        with pytest.raises(ValueError, match="titre"):
            store.validate_reminder(reminder(title=title))
    legacy = store.validate_reminder(reminder(title="", message="  Ancien\nrappel 🎯  "))
    assert legacy.title == "Ancien rappel 🎯" and legacy.message == "Ancien\nrappel 🎯"
    titled = store.validate_reminder(reminder(title="🌙" * 80, personal_number=10**18))
    assert titled.label.startswith(f"#{10**18} · ")
    assert len(titled.label.encode("utf-16-le")) // 2 <= 100


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


@pytest.mark.parametrize("editing", [False, True])
@pytest.mark.parametrize("channel_choice", ["menu", "current"])
def test_review_mentions_can_switch_a_dm_to_channel_and_save_selected_members(monkeypatch, editing, channel_choice):
    async def scenario():
        wizard = editor.ReminderEditor(reminder(channel_id=None), step=4, editing=editing)
        create, edit = AsyncMock(return_value=1), AsyncMock(return_value=True)
        monkeypatch.setattr(store, "create_reminder", create)
        monkeypatch.setattr(store, "edit_reminder", edit)
        monkeypatch.setattr(store, "get_owned_reminder", AsyncMock(return_value=reminder(recipient_ids=(4,))))
        button = next(item for item in wizard.children if isinstance(item, discord.ui.Button) and item.label == "Mentions")
        assert not button.disabled
        assert not any(isinstance(item, discord.ui.Select) for item in wizard.children)
        assert all(field.name != "Catégorie" for field in wizard.embed().fields)
        await button.callback(interaction())
        assert wizard.step == 3
        assert "message privé" in wizard.embed().description
        selector = next(item for item in wizard.children if isinstance(item, discord.ui.ChannelSelect))
        inter = interaction()
        if channel_choice == "menu":
            inter.data = {"values": ["3"]}
            await selector.callback(inter)
        else:
            await wizard.use_current_channel(inter)
        assert wizard.step == 3 and wizard.draft.channel_id == 3
        users = next(item for item in wizard.children if isinstance(item, discord.ui.UserSelect))
        inter = interaction()
        inter.data = {"values": ["4"]}
        await users.callback(inter)
        await wizard.next(interaction())
        assert wizard.step == 4 and wizard.draft.recipient_ids == (4,)
        assert any("<@4>" in field.value for field in wizard.embed().fields)
        await wizard.save(interaction())
        saved = edit.await_args.args[0] if editing else create.await_args.args[0]
        assert saved.channel_id == 3 and saved.recipient_ids == (4,)
        (create if editing else edit).assert_not_awaited()
    asyncio.run(scenario())


def test_mentions_destination_checks_permissions_before_replacing_the_dm_draft():
    async def scenario():
        wizard = editor.ReminderEditor(reminder(channel_id=None), step=3)
        inter = interaction()
        inter.data = {"values": ["3"]}
        inter.channel.permissions_for.return_value = discord.Permissions.none()
        with pytest.raises(ValueError, match="salon de destination"):
            await wizard.choose_channel(inter)
        assert wizard.draft.channel_id is None and wizard.draft.recipient_ids == ()
    asyncio.run(scenario())


def test_legacy_categories_are_not_shown_in_the_dashboard_or_reminder_cards():
    async def scenario():
        record = reminder(category="deadline", message="Vérifie les annonces")
        dashboard = views.ReminderDashboard(1, 2, [record], {"timezone": "Europe/Brussels", "generation": 0})
        details = views.ReminderDetails(record)
        for embed in (dashboard.embed(), details.embed()):
            assert "Échéance" not in str(embed.to_dict())
            assert all(field.name != "Catégorie" for field in embed.fields)
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


def test_only_reminder_command_opens_the_private_manager_without_arguments(monkeypatch):
    async def scenario():
        from discord.ext import commands
        dashboard = views.ReminderDashboard(1, 2, [], {"timezone": "Europe/Brussels", "generation": 0})
        load = AsyncMock(return_value=dashboard)
        monkeypatch.setattr(command.ReminderDashboard, "load", load)
        inter = interaction()
        async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
            await command.register(bot)
            action = bot.tree.get_command("reminder")
            assert not isinstance(action, discord.app_commands.Group)
            assert action.parameters == []
            await action.callback(inter)
        load.assert_awaited_once_with(1, 2, guild=inter.guild)
        inter.response.defer.assert_awaited_once_with(ephemeral=True)
        sent = inter.followup.send.await_args.kwargs
        assert sent["view"] is dashboard and sent["ephemeral"]
    asyncio.run(scenario())


def test_manager_command_errors_reply_once_without_a_false_technical_alert(monkeypatch):
    async def scenario():
        from discord import app_commands
        from discord.ext import commands
        from src.utils import command_errors, reminder_ui

        report = AsyncMock()
        monkeypatch.setattr(reminder_ui, "report_error", report)
        monkeypatch.setattr(command_errors, "report_error", report)
        monkeypatch.setattr(command.ReminderDashboard, "load", AsyncMock(side_effect=ValueError("Session indisponible")))
        inter = interaction()
        async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
            await command.register(bot)
            action = bot.tree.get_command("reminder")
            inter.command = action
            with pytest.raises(app_commands.CommandInvokeError) as caught:
                await action._invoke_with_namespace(inter, SimpleNamespace())
            await action._invoke_error_handlers(inter, caught.value)
            await command_errors.handle_app_command_error(bot, inter, caught.value)
        report.assert_not_awaited()
        inter.followup.send.assert_awaited_once()
        assert "Session indisponible" in inter.followup.send.await_args.args[0]
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
