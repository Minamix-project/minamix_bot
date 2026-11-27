"""Optional advance notices share ownership and lifecycle with the main reminder."""

import asyncio
from dataclasses import replace
import os
import time
from unittest.mock import AsyncMock

import discord
import pytest

from src.core.db_init import init_db
from src.events import reminder_handler as handler
from src.utils import reminder_delivery as delivery
from src.utils import reminder_editor as editor
from src.utils import reminders as store
from test_reminder_delivery import reminder, setup_destination
from test_reminder_manager import interaction
from test_reminder_manager_storage import connect


def test_advance_notice_choices_are_optional_and_visible_in_date_and_review():
    async def scenario():
        wizard = editor.ReminderEditor(reminder(due_at=int(time.time()) + 4 * 3600), step=1)
        select = next(item for item in wizard.children if isinstance(item, discord.ui.Select) and item.row == 1)
        assert [option.value for option in select.options] == ["0", "10", "30", "60", "120"]
        assert [option.value for option in select.options if option.default] == ["0"]
        assert wizard.draft.advance_minutes == 0
        inter = interaction()
        inter.data = {"values": ["120"]}
        await select.callback(inter)
        assert wizard.draft.advance_minutes == 120
        assert "2 heures avant" in next(field.value for field in wizard.embed().fields if field.name == "Pré-rappel")
        wizard.step = 4
        wizard.build()
        advance = next(item for item in wizard.children if isinstance(item, discord.ui.Button) and item.label == "Pré-rappel")
        await advance.callback(interaction())
        assert wizard.step == 1 and wizard.draft.advance_minutes == 120
        wizard.draft = replace(wizard.draft, advance_status="sent", advance_sent_at=int(time.time()))
        inter = interaction()
        inter.data = {"values": ["demain 18:00"]}
        await wizard.choose_time(inter)
        assert wizard.draft.advance_status == "pending" and wizard.draft.advance_sent_at is None
        inter = interaction()
        inter.data = {"values": ["0"]}
        await wizard.choose_advance(inter)
        assert wizard.draft.advance_minutes == 0 and wizard.draft.advance_status == "disabled"
    asyncio.run(scenario())


def test_an_elapsed_advance_notice_cannot_be_selected_or_saved_for_a_new_schedule(monkeypatch):
    async def scenario():
        wizard = editor.ReminderEditor(reminder(due_at=int(time.time()) + 300), step=1)
        inter = interaction()
        inter.data = {"values": ["10"]}
        with pytest.raises(ValueError, match="déjà passé"):
            await wizard.choose_advance(inter)
        assert wizard.draft.advance_minutes == 0
        inter.response.edit_message.assert_awaited_once()
        create = AsyncMock()
        monkeypatch.setattr(store, "create_reminder", create)
        wizard.draft = replace(wizard.draft, advance_minutes=10)
        with pytest.raises(ValueError, match="déjà passé"):
            await wizard.save(interaction())
        create.assert_not_awaited()
        with pytest.raises(ValueError):
            store.validate_reminder(reminder(advance_minutes=15))
    asyncio.run(scenario())


@pytest.mark.parametrize("channel_id", [None, 3])
def test_advance_delivery_uses_the_original_destination_mentions_and_main_date_without_snooze_buttons(channel_id):
    async def scenario():
        bot, _guild, owner, _guest, channel = setup_destination()
        record = reminder(channel_id=channel_id, delivery_kind="advance", advance_minutes=30,
                          recipient_ids=(4,) if channel_id else ())
        await delivery.send_reminder(bot, record)
        sent = (channel.send if channel_id else owner.send).await_args.kwargs
        assert sent["embed"].title.startswith("🔔 Pré-rappel · ")
        assert sent["embed"].description == record.message
        assert sent["embed"].fields[0].name == "Rappel principal prévu pour"
        assert str(record.due_at) in sent["embed"].fields[0].value
        assert sent["view"] is None
        assert sent["allowed_mentions"].to_dict()["users"] == ([2, 4] if channel_id else [2])
        assert sent["allowed_mentions"].to_dict()["parse"] == []
    asyncio.run(scenario())


def test_advance_failure_notification_says_the_main_reminder_is_still_scheduled():
    async def scenario():
        bot, _guild, owner, _guest, _channel = setup_destination()
        bot.get_user.return_value = owner
        await handler.notify_failure(bot, reminder(delivery_kind="advance"))
        text = owner.send.await_args.args[0]
        assert "pré-rappel" in text and "principal reste programmé" in text
    asyncio.run(scenario())


async def prepare_database():
    db = await connect()
    try:
        await init_db(db)
        async with db.cursor() as cursor:
            await cursor.execute("DELETE FROM guild_reminders")
            await cursor.execute("DELETE FROM reminder_preferences")
    finally:
        db.close()


mysql_only = pytest.mark.skipif(not os.getenv("REMINDER_TEST_DB_PORT"), reason="Requires a disposable MySQL test database")


@mysql_only
@pytest.mark.parametrize("minutes", [0, 10, 30, 60, 120])
def test_mysql_each_preset_sends_once_before_the_main_reminder_without_an_extra_number(monkeypatch, minutes):
    monkeypatch.setattr(store, "get_db_connection", connect)

    async def scenario():
        await prepare_database()
        due_at = int(time.time()) + 4 * 3600
        rid = await store.create_reminder(reminder(id=0, due_at=due_at, advance_minutes=minutes))
        saved = await store.get_reminder(rid, 1, 2)
        assert saved.reference == 1 and saved.advance_minutes == minutes
        first_time = due_at - minutes * 60
        assert await store.claim_next_reminder(first_time - 1, {1}) is None
        claims = await asyncio.gather(*(store.claim_next_reminder(first_time, {1}) for _ in range(4)))
        winners = [record for record in claims if record is not None]
        assert len(winners) == 1 and winners[0].attempts == 1
        first = winners[0]
        assert first.delivery_kind == ("advance" if minutes else "main")
        assert not await store.delete_reminder(rid, 1, 2)
        assert not await store.edit_reminder(saved)
        assert await store.finish_reminder(first, first_time)
        assert await store.claim_next_reminder(first_time, {1}) is None
        if minutes:
            pending = await store.get_reminder(rid, 1, 2)
            assert pending.status == "pending" and pending.advance_status == "sent"
            assert pending.advance_sent_at == first_time and pending.attempts == 0
            assert len(await store.list_reminders(1, 2, tab="pending")) == 1
            assert await store.list_reminders(1, 2, tab="sent") == []
            assert await store.claim_next_reminder(due_at - 1, {1}) is None
            main = await store.claim_next_reminder(due_at, {1})
            assert main.delivery_kind == "main" and main.attempts == 1
            assert await store.finish_reminder(main, due_at)
        sent = await store.get_owned_reminder(rid, 1, 2)
        assert sent.status == "sent" and sent.reference == 1
        assert len(await store.list_reminders(1, 2, tab="sent")) == 1
        assert (await store.get_preferences(1, 2))["next_number"] == 2
    asyncio.run(scenario())


@mysql_only
def test_mysql_notice_failure_does_not_cancel_or_postpone_the_main_delivery(monkeypatch):
    monkeypatch.setattr(store, "get_db_connection", connect)

    async def scenario():
        await prepare_database()
        due_at = int(time.time()) + 3600
        rid = await store.create_reminder(reminder(id=0, due_at=due_at, advance_minutes=30))
        advance = await store.claim_next_reminder(due_at - 1800, {1})
        assert await store.finish_reminder(advance, due_at - 1800, error="Destination indisponible", permanent=True)
        record = await store.get_reminder(rid, 1, 2)
        assert record.status == "pending" and record.advance_status == "failed"
        assert record.last_error is None and record.advance_last_error == "Destination indisponible"
        main = await store.claim_next_reminder(due_at, {1})
        assert main.id == rid and main.delivery_kind == "main" and main.attempts == 1
        await store.finish_reminder(main, due_at)
        # Retry delays for a notice must not delay a main delivery now due.
        due_at += 7200
        rid = await store.create_reminder(reminder(id=0, due_at=due_at, advance_minutes=10))
        when = due_at - 600
        for delay in (120, 240, 480):
            record = await store.claim_next_reminder(when, {1})
            assert record.id == rid and record.delivery_kind == "advance"
            await store.finish_reminder(record, when, error="Échec temporaire")
            when += delay
        assert when > due_at
        main = await store.claim_next_reminder(due_at, {1})
        assert main.id == rid and main.delivery_kind == "main" and main.attempts == 1
        assert main.advance_status == "skipped"
        assert not await store.finish_reminder(record, due_at)
    asyncio.run(scenario())


@mysql_only
def test_mysql_restarts_recover_notice_leases_but_skip_obsolete_notices(monkeypatch):
    monkeypatch.setattr(store, "get_db_connection", connect)

    async def scenario():
        await prepare_database()
        due_at = int(time.time()) + 7200
        rid = await store.create_reminder(reminder(id=0, due_at=due_at, advance_minutes=30))
        when = due_at - 1800
        old = await store.claim_next_reminder(when, {1})
        assert await store.claim_next_reminder(when + store.LEASE_SECONDS - 1, {1}) is None
        recovered = await store.claim_next_reminder(when + store.LEASE_SECONDS, {1})
        assert recovered.id == rid and recovered.delivery_kind == "advance" and recovered.attempts == 2
        assert not await store.finish_reminder(old, when + store.LEASE_SECONDS)
        await store.finish_reminder(recovered, when + store.LEASE_SECONDS)
        main = await store.claim_next_reminder(due_at, {1})
        await store.finish_reminder(main, due_at)
        # A restart after the main date sends only the main reminder.
        due_at += 3600
        rid = await store.create_reminder(reminder(id=0, due_at=due_at, advance_minutes=10))
        overdue = await store.claim_next_reminder(due_at + 5, {1})
        assert overdue.id == rid and overdue.delivery_kind == "main" and overdue.advance_status == "skipped"
    asyncio.run(scenario())


@mysql_only
def test_mysql_edits_reports_disabling_deletion_and_reset_keep_notices_coherent(monkeypatch):
    monkeypatch.setattr(store, "get_db_connection", connect)

    async def scenario():
        await prepare_database()
        due_at = int(time.time()) + 7200
        rid = await store.create_reminder(reminder(id=0, due_at=due_at, advance_minutes=30))
        before = await store.get_reminder(rid, 1, 2)
        advance = await store.claim_next_reminder(due_at - 1800, {1})
        await store.finish_reminder(advance, due_at - 1800)
        # A draft opened before sending must not re-arm an already sent notice.
        assert await store.edit_reminder(replace(before, title="Nouveau titre"))
        after = await store.get_reminder(rid, 1, 2)
        assert after.advance_status == "sent" and after.title == "Nouveau titre"
        assert await store.claim_next_reminder(due_at - 1799, {1}) is None
        new_date = due_at + 14400
        assert await store.edit_reminder(replace(after, due_at=new_date))
        after = await store.get_reminder(rid, 1, 2)
        assert after.advance_status == "pending" and after.advance_at == new_date - 1800
        assert await store.edit_reminder(replace(after, advance_minutes=0))
        after = await store.get_reminder(rid, 1, 2)
        assert after.advance_status == "disabled"
        assert await store.claim_next_reminder(new_date - 1800, {1}) is None
        assert await store.edit_reminder(replace(after, advance_minutes=30))
        after = await store.get_reminder(rid, 1, 2)
        assert await store.edit_reminder(replace(after, due_at=int(time.time()) + 600))
        after = await store.get_reminder(rid, 1, 2)
        assert after.advance_status == "skipped"
        assert await store.delete_reminder(rid, 1, 2)
        assert await store.claim_next_reminder(new_date, {1}) is None
        # A short report of a delivered reminder keeps the main send, skips the impossible notice.
        rid = await store.create_reminder(reminder(id=0, due_at=due_at, advance_minutes=30))
        main = await store.claim_next_reminder(due_at, {1})
        await store.finish_reminder(main, due_at)
        source = await store.get_owned_reminder(rid, 1, 2)
        child = await store.snooze_reminder(source, int(time.time()) + 600)
        report = await store.get_reminder(child, 1, 2)
        assert report.advance_minutes == 30 and report.advance_status == "skipped"
        expected = ((report.id, report.revision, report.status),)
        prefs = await store.get_preferences(1, 2)
        await store.reset_reminders(1, 2, prefs["generation"], expected)
        assert await store.claim_next_reminder(new_date + 1000, {1}) is None
    asyncio.run(scenario())
