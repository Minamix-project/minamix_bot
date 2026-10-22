"""Optional integration test against a disposable MySQL 8 database.

Set REMINDER_TEST_DB_PORT to a localhost port for an isolated, empty-password
MySQL instance containing the reminder_test database. Production DB settings
are deliberately ignored.
"""

import asyncio
from dataclasses import replace
import os
import time

import aiomysql
import pytest

from src.core.db_init import init_db
from src.utils import reminders as store


@pytest.mark.skipif(not os.getenv("REMINDER_TEST_DB_PORT"), reason="Requires a disposable MySQL test database")
def test_mysql_reminder_lifecycle_and_concurrency(monkeypatch):
    async def connect():
        return await aiomysql.connect(
            host="127.0.0.1", port=int(os.environ["REMINDER_TEST_DB_PORT"]),
            user="root", password="", db="reminder_test", autocommit=True, charset="utf8mb4",
        )

    monkeypatch.setattr(store, "get_db_connection", connect)

    async def scenario():
        db = await connect()
        try:
            # Both a fresh installation and an existing installation must work.
            await init_db(db)
            await init_db(db)
            async with db.cursor() as cursor:
                await cursor.execute("DELETE FROM guild_reminders")
        finally:
            db.close()

        now = int(time.time())
        original = store.Reminder(1, 2, 3, now + 3600, "Reminder with unicode: réunion 🎲", recipient_ids=(4,))
        reminder_id = await store.create_reminder(original)
        assert await store.list_reminders(1, 999) == []
        assert await store.list_reminders(999, 2) == []
        assert await store.get_reminder(reminder_id, 999, 2) is None
        assert await store.get_reminder(reminder_id, 1, 999) is None
        assert not await store.delete_reminder(reminder_id, 999, 2)
        assert not await store.delete_reminder(reminder_id, 1, 999)
        assert await store.claim_next_reminder(now, {1}) is None

        saved = await store.get_reminder(reminder_id, 1, 2)
        assert saved.message == original.message
        assert saved.recipient_ids == (4,)
        # No-op edits succeed, while stale concurrent edits cannot overwrite them.
        assert await store.edit_reminder(saved)
        assert not await store.edit_reminder(replace(saved, message="Stale update"))
        saved = await store.get_reminder(reminder_id, 1, 2)
        assert await store.edit_reminder(replace(saved, due_at=now - 1))
        assert await store.claim_next_reminder(now, {999}) is None
        assert await store.claim_next_reminder(now, set()) is None

        results = await asyncio.gather(*(store.claim_next_reminder(now, {1}) for _ in range(4)))
        claims = [result for result in results if result is not None]
        assert len(claims) == 1
        first = claims[0]
        assert first.attempts == 1
        assert not await store.delete_reminder(reminder_id, 1, 2)
        assert not await store.edit_reminder(saved)
        assert await store.claim_next_reminder(now + store.LEASE_SECONDS - 1, {1}) is None

        # A restart recovers an expired lease; the old worker cannot finalize it.
        recovered = await store.claim_next_reminder(now + store.LEASE_SECONDS, {1})
        assert recovered.id == reminder_id and recovered.attempts == 2
        assert recovered.claim_token != first.claim_token
        assert not await store.finish_reminder(first, now)
        assert await store.finish_reminder(recovered, now, error="Temporary failure")
        assert await store.claim_next_reminder(now, {1}) is None
        retry = await store.claim_next_reminder(now + 3600, {1})
        assert retry.id == reminder_id and retry.attempts == 3
        assert await store.finish_reminder(retry, now, error="No access", permanent=True)
        failed = await store.get_reminder(reminder_id, 1, 2)
        assert failed.status == "failed" and failed.last_error == "No access"

        # Editing a failure resets retries and delivery goes through once.
        assert await store.edit_reminder(replace(failed, message="Corrected"))
        retry = await store.claim_next_reminder(now, {1})
        assert retry.attempts == 1
        assert await store.finish_reminder(retry, now)
        assert not await store.finish_reminder(retry, now)
        assert await store.list_reminders(1, 2) == []
        assert await store.claim_next_reminder(now + 9999, {1}) is None

        # Temporary failures stop after five attempts.
        terminal_id = await store.create_reminder(replace(original, due_at=now - 1))
        for attempt in range(1, store.MAX_ATTEMPTS + 1):
            attempt_time = now + attempt * 4000
            claimed = await store.claim_next_reminder(attempt_time, {1})
            assert claimed.id == terminal_id and claimed.attempts == attempt
            await store.finish_reminder(claimed, attempt_time, error="Temporary failure")
        assert (await store.get_reminder(terminal_id, 1, 2)).status == "failed"
        assert await store.claim_next_reminder(now + 99999, {1}) is None
        assert await store.delete_reminder(terminal_id, 1, 2)

        # Retention cleanup removes completed reminders but leaves pending ones.
        pending_id = await store.create_reminder(original)
        await store.purge_finished_reminders(now + 31 * 86400)
        assert (await store.get_reminder(pending_id, 1, 2)).status == "pending"
        db = await connect()
        try:
            async with db.cursor() as cursor:
                await cursor.execute("SELECT COUNT(*) FROM guild_reminders WHERE id = %s", (reminder_id,))
                assert (await cursor.fetchone())[0] == 0
        finally:
            db.close()
        assert await store.delete_reminder(pending_id, 1, 2)

    asyncio.run(scenario())
