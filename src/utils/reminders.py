"""Persistent reminder storage with ownership checks and recoverable delivery leases."""

from dataclasses import dataclass, replace
import json
import secrets

import aiomysql

from src.utils.db import get_db_connection

MAX_ATTEMPTS = 5
LEASE_SECONDS = 300
CATEGORIES = {
    "custom": "Reminder",
    "staff_meeting": "Staff meeting",
    "deadline": "Deadline",
    "ooc_event": "OOC event",
    "rp_event": "RP event",
}


@dataclass(frozen=True)
class Reminder:
    guild_id: int
    user_id: int
    channel_id: int | None
    due_at: int
    message: str
    category: str = "custom"
    mention_owner: bool = True
    recipient_ids: tuple[int, ...] = ()
    id: int = 0
    status: str = "pending"
    attempts: int = 0
    revision: int = 0
    claim_token: str | None = None
    last_error: str | None = None


def _from_row(row) -> Reminder:
    fields = {name: row[name] for name in Reminder.__dataclass_fields__ if name in row}
    fields["recipient_ids"] = tuple(json.loads(row["recipient_ids"]))
    return Reminder(**fields)


def validate_reminder(reminder: Reminder) -> Reminder:
    message = reminder.message.strip()
    if not message or len(message) > 1000:
        raise ValueError("Reminder text must contain between 1 and 1,000 characters.")
    if reminder.category not in CATEGORIES:
        raise ValueError("Unknown reminder category.")
    recipients = tuple(dict.fromkeys(reminder.recipient_ids))
    if len(recipients) > 10:
        raise ValueError("Select at most 10 additional members.")
    if reminder.channel_id is None and recipients:
        raise ValueError("Additional mentions require channel delivery. DMs are sent only to you.")
    return replace(reminder, message=message, recipient_ids=recipients)


def _values(reminder: Reminder) -> tuple:
    return (
        reminder.channel_id, reminder.due_at, reminder.message, reminder.category,
        reminder.mention_owner, json.dumps(reminder.recipient_ids),
    )


async def create_reminder(reminder: Reminder) -> int:
    reminder = validate_reminder(reminder)
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO guild_reminders "
                "(channel_id, due_at, message, category, mention_owner, recipient_ids, guild_id, user_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (*_values(reminder), reminder.guild_id, reminder.user_id),
            )
            return cursor.lastrowid
    finally:
        db.close()


async def list_reminders(guild_id: int, user_id: int) -> list[Reminder]:
    db = await get_db_connection()
    try:
        async with db.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT * FROM guild_reminders WHERE guild_id = %s AND user_id = %s "
                "AND status IN ('pending', 'sending', 'failed') ORDER BY due_at, id",
                (guild_id, user_id),
            )
            return [_from_row(row) for row in await cursor.fetchall()]
    finally:
        db.close()


async def get_reminder(reminder_id: int, guild_id: int, user_id: int) -> Reminder | None:
    db = await get_db_connection()
    try:
        async with db.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT * FROM guild_reminders WHERE id = %s AND guild_id = %s AND user_id = %s "
                "AND status IN ('pending', 'failed')",
                (reminder_id, guild_id, user_id),
            )
            row = await cursor.fetchone()
            return _from_row(row) if row else None
    finally:
        db.close()


async def edit_reminder(reminder: Reminder) -> bool:
    reminder = validate_reminder(reminder)
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "UPDATE guild_reminders SET channel_id = %s, due_at = %s, message = %s, "
                "category = %s, mention_owner = %s, recipient_ids = %s, status = 'pending', "
                "attempts = 0, next_attempt_at = 0, claim_token = NULL, claimed_until = 0, "
                "last_error = NULL, finished_at = NULL, revision = revision + 1 "
                "WHERE id = %s AND guild_id = %s AND user_id = %s AND revision = %s "
                "AND status IN ('pending', 'failed')",
                (*_values(reminder), reminder.id, reminder.guild_id, reminder.user_id, reminder.revision),
            )
            return cursor.rowcount == 1
    finally:
        db.close()


async def delete_reminder(reminder_id: int, guild_id: int, user_id: int) -> bool:
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "DELETE FROM guild_reminders WHERE id = %s AND guild_id = %s AND user_id = %s "
                "AND status IN ('pending', 'failed')",
                (reminder_id, guild_id, user_id),
            )
            return cursor.rowcount == 1
    finally:
        db.close()


async def claim_next_reminder(now: int, guild_ids: set[int]) -> Reminder | None:
    if not guild_ids:
        return None
    token = secrets.token_hex(16)
    db = await get_db_connection()
    try:
        async with db.cursor(aiomysql.DictCursor) as cursor:
            # The conditional UPDATE is atomic across workers. Expired leases
            # recover reminders interrupted by a process restart.
            placeholders = ", ".join("%s" for _ in guild_ids)
            await cursor.execute(
                "UPDATE guild_reminders SET status = 'sending', claim_token = %s, "
                "claimed_until = %s, attempts = attempts + 1 "
                f"WHERE guild_id IN ({placeholders}) AND due_at <= %s AND next_attempt_at <= %s "
                "AND (status = 'pending' OR (status = 'sending' AND claimed_until <= %s)) "
                "ORDER BY due_at, id LIMIT 1",
                (token, now + LEASE_SECONDS, *sorted(guild_ids), now, now, now),
            )
            if cursor.rowcount != 1:
                return None
            await cursor.execute("SELECT * FROM guild_reminders WHERE claim_token = %s", (token,))
            return _from_row(await cursor.fetchone())
    finally:
        db.close()


async def finish_reminder(reminder: Reminder, now: int, *, error: str | None = None,
                          permanent: bool = False) -> bool:
    status = "sent" if error is None else (
        "failed" if permanent or reminder.attempts >= MAX_ATTEMPTS else "pending"
    )
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "UPDATE guild_reminders SET status = %s, last_error = %s, next_attempt_at = %s, "
                "finished_at = %s, claim_token = NULL, claimed_until = 0 "
                "WHERE id = %s AND status = 'sending' AND claim_token = %s",
                (status, error, now + min(3600, 60 * 2 ** min(reminder.attempts, 6)),
                 now if status in {"sent", "failed"} else None, reminder.id, reminder.claim_token),
            )
            return cursor.rowcount == 1
    finally:
        db.close()


async def purge_finished_reminders(now: int) -> None:
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "DELETE FROM guild_reminders WHERE status IN ('sent', 'failed') AND finished_at < %s",
                (now - 30 * 86400,),
            )
    finally:
        db.close()
