"""Real MySQL migration, personal numbering, reset isolation and stale-action safety."""

import asyncio
from dataclasses import replace
import os
from pathlib import Path
import time

import aiomysql
import pytest

from src.core.db_init import init_db
from src.utils import reminders as store

pytestmark = pytest.mark.skipif(not os.getenv("REMINDER_TEST_DB_PORT"), reason="Requires a disposable MySQL test database")


async def connect(database="reminder_test"):
    return await aiomysql.connect(host="127.0.0.1", port=int(os.environ["REMINDER_TEST_DB_PORT"]), user="root", password="",
                                  db=database, autocommit=True, charset="utf8mb4")


def test_mysql_personal_numbering_reset_preserves_other_users_and_history_and_invalidates_old_actions(monkeypatch):
    monkeypatch.setattr(store, "get_db_connection", connect)

    async def scenario():
        db = await connect()
        try:
            await init_db(db)
            async with db.cursor() as cursor:
                await cursor.execute("DELETE FROM guild_reminders")
                await cursor.execute("DELETE FROM reminder_preferences")
        finally:
            db.close()
        original = store.Reminder(1, 2, None, int(time.time()) + 3600, "Ancien rappel 🎯")
        first = await store.create_reminder(original)
        second = await store.create_reminder(original)
        other_user = await store.create_reminder(replace(original, user_id=3))
        other_server = await store.create_reminder(replace(original, guild_id=999))
        assert (await store.get_reminder(first, 1, 2)).reference == 1
        assert (await store.get_reminder(second, 1, 2)).reference == 2
        assert (await store.get_reminder(other_user, 1, 3)).reference == 1
        assert (await store.get_reminder(other_server, 999, 2)).reference == 1
        assert await store.get_owned_reminder(first, 1, 3) is None
        assert (await store.resolve_reminder("#1", 1, 2)).id == first
        assert (await store.resolve_reminder(f"r:{second}", 1, 2)).id == second
        ids = await asyncio.gather(*(store.create_reminder(original) for _ in range(5)))
        numbers = [(await store.get_reminder(value, 1, 2)).reference for value in ids]
        assert sorted(numbers) == [3, 4, 5, 6, 7]
        await store.save_timezone(1, 2, "America/Montreal")
        assert (await store.get_preferences(1, 3))["timezone"] == "Europe/Brussels"
        with pytest.raises(ValueError):
            await store.save_timezone(1, 2, "Invalid/Timezone")
        db = await connect()
        try:
            async with db.cursor() as cursor:
                await cursor.execute("UPDATE guild_reminders SET status = 'sent', finished_at = %s WHERE id = %s", (int(time.time()), first))
        finally:
            db.close()
        source = await store.get_owned_reminder(first, 1, 2)
        reports = await asyncio.gather(*(store.snooze_reminder(source, int(time.time()) + 600) for _ in range(4)), return_exceptions=True)
        assert len([value for value in reports if isinstance(value, int)]) == 1
        assert all(isinstance(value, (int, ValueError)) for value in reports)
        active = await store.list_reminders(1, 2)
        expected = tuple(sorted((record.id, record.revision, record.status) for record in active))
        added = await store.create_reminder(original)
        with pytest.raises(ValueError, match="liste a changé"):
            await store.reset_reminders(1, 2, 0, expected)
        assert await store.delete_reminder(added, 1, 2)
        db = await connect()
        try:
            async with db.cursor() as cursor:
                await cursor.execute("UPDATE guild_reminders SET status = 'sending' WHERE id = %s", (second,))
            with pytest.raises(ValueError, match="cours d'envoi"):
                await store.reset_reminders(1, 2, 0, expected)
            async with db.cursor() as cursor:
                await cursor.execute("UPDATE guild_reminders SET status = 'pending' WHERE id = %s", (second,))
        finally:
            db.close()
        assert await store.reset_reminders(1, 2, 0, expected) == len(active)
        assert (await store.get_preferences(1, 2))["timezone"] == "America/Montreal"
        assert await store.get_reminder(other_user, 1, 3)
        assert await store.get_reminder(other_server, 999, 2)
        assert [record.id for record in await store.list_reminders(1, 2, tab="sent")] == [first]
        new_id = await store.create_reminder(original)
        new = await store.get_reminder(new_id, 1, 2)
        assert new.reference == 1 and new.generation == 1 and new.id != first
        assert (await store.resolve_reminder("#1", 1, 2)).id == new_id
        assert await store.get_owned_reminder(first, 1, 2, current_only=True) is None
        with pytest.raises(ValueError):
            await store.create_reminder(original, expected_generation=0)
        with pytest.raises(ValueError):
            await store.snooze_reminder(source, int(time.time()) + 600)
        with pytest.raises(ValueError):
            await store.reset_reminders(1, 2, 0, ())
        assert await store.edit_reminder(replace(new, message="Texte modifié"))
        assert not await store.delete_reminder(new_id, 1, 2, revision=new.revision)
        assert await store.delete_reminder(new_id, 1, 2, revision=new.revision + 1)
    asyncio.run(scenario())


def test_mysql_number_allocation_rolls_back_when_creation_commit_fails(monkeypatch):
    monkeypatch.setattr(store, "get_db_connection", connect)

    async def scenario():
        original = store.Reminder(1234, 555, None, int(time.time()) + 3600, "Ne pas perdre le numéro")
        before = await store.get_preferences(1234, 555)

        async def failing_connection():
            db = await connect()

            async def fail():
                raise RuntimeError("Commit failed")
            db.commit = fail
            return db

        monkeypatch.setattr(store, "get_db_connection", failing_connection)
        with pytest.raises(RuntimeError):
            await store.create_reminder(original)
        monkeypatch.setattr(store, "get_db_connection", connect)
        assert (await store.get_preferences(1234, 555))["next_number"] == before["next_number"]
        assert not await store.list_reminders(1234, 555)
    asyncio.run(scenario())


def test_mysql_upgrade_preserves_reminder_contents_global_ids_schedules_and_delivery_state(monkeypatch, tmp_path):
    from src.core import schema_migrations
    current = Path("src/migrations")
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    for path in current.glob("*.sql"):
        if path.name < "0022":
            (legacy / path.name).write_text(path.read_text())

    async def scenario():
        admin = await connect()
        db = None
        try:
            async with admin.cursor() as cursor:
                await cursor.execute("CREATE DATABASE reminder_manager_upgrade_test CHARACTER SET utf8mb4")
            db = await connect("reminder_manager_upgrade_test")
            monkeypatch.setattr(schema_migrations, "MIGRATIONS_DIR", legacy)
            await init_db(db)
            async with db.cursor() as cursor:
                for rid, gid, uid in [(100, 1, 2), (150, 1, 2), (20, 1, 3), (30, 999, 2)]:
                    await cursor.execute("INSERT INTO guild_reminders (id, guild_id, user_id, channel_id, due_at, message, recipient_ids) "
                                         "VALUES (%s, %s, %s, 77, 2000000000, 'Réunion existante 🎯', JSON_ARRAY(7))", (rid, gid, uid))
                await cursor.execute("UPDATE guild_reminders SET status = 'sending', claim_token = 'existing-claim', claimed_until = 2000000300, attempts = 2 WHERE id = 150")
            monkeypatch.setattr(schema_migrations, "MIGRATIONS_DIR", current)
            await init_db(db)
            await init_db(db)
            async with db.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM guild_reminders ORDER BY id")
                rows = await cursor.fetchall()
                assert [row["id"] for row in rows] == [20, 30, 100, 150]
                assert [row["personal_number"] for row in rows] == [1, 1, 1, 2]
                assert all(row["message"] == "Réunion existante 🎯" and row["due_at"] == 2000000000 for row in rows)
                assert rows[-1]["claim_token"] == "existing-claim" and rows[-1]["attempts"] == 2 and rows[-1]["status"] == "sending"
                await cursor.execute("SELECT next_number FROM reminder_preferences WHERE guild_id = 1 AND user_id = 2")
                assert (await cursor.fetchone())["next_number"] == 3
        finally:
            if db:
                db.close()
            async with admin.cursor() as cursor:
                await cursor.execute("DROP DATABASE IF EXISTS reminder_manager_upgrade_test")
            admin.close()
    asyncio.run(scenario())
