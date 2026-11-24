"""Persistent reminder storage with ownership checks and recoverable delivery leases."""

from dataclasses import dataclass, replace
import json
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiomysql

from src.utils.db import get_db_connection

MAX_ATTEMPTS = 5
LEASE_SECONDS = 300
CATEGORIES = {
    "custom": "Rappel personnalisé",
    "staff_meeting": "Réunion du staff",
    "deadline": "Échéance",
    "ooc_event": "Événement HRP",
    "rp_event": "Événement RP",
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
    personal_number: int = 0
    generation: int = 0
    timezone: str = "Europe/Brussels"
    parent_id: int | None = None

    @property
    def reference(self):
        return self.personal_number or self.id


def _from_row(row) -> Reminder:
    fields = {name: row[name] for name in Reminder.__dataclass_fields__ if name in row}
    fields["recipient_ids"] = tuple(json.loads(row["recipient_ids"]))
    return Reminder(**fields)


def validate_reminder(reminder: Reminder) -> Reminder:
    message = reminder.message.strip()
    if not message or len(message) > 1000:
        raise ValueError("Le texte du rappel doit contenir entre 1 et 1 000 caractères.")
    if reminder.category not in CATEGORIES:
        raise ValueError("Catégorie de rappel inconnue.")
    recipients = tuple(dict.fromkeys(reminder.recipient_ids))
    if len(recipients) > 10:
        raise ValueError("Sélectionne au maximum 10 membres supplémentaires.")
    if reminder.channel_id is None and recipients:
        raise ValueError("Les mentions supplémentaires nécessitent un envoi dans un salon. Les MP te sont réservés.")
    return replace(reminder, message=message, recipient_ids=recipients)


def _values(reminder: Reminder) -> tuple:
    return (
        reminder.channel_id, reminder.due_at, reminder.message, reminder.category,
        reminder.mention_owner, json.dumps(reminder.recipient_ids), reminder.timezone,
    )


async def _preferences(cursor, guild_id, user_id, *, lock=False):
    await cursor.execute(
        "INSERT INTO reminder_preferences (guild_id, user_id) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE user_id = reminder_preferences.user_id", (guild_id, user_id),
    )
    await cursor.execute("SELECT * FROM reminder_preferences WHERE guild_id = %s AND user_id = %s" +
                         (" FOR UPDATE" if lock else ""), (guild_id, user_id))
    return await cursor.fetchone()


async def get_preferences(guild_id, user_id):
    db = await get_db_connection()
    try:
        async with db.cursor(aiomysql.DictCursor) as cursor:
            return await _preferences(cursor, guild_id, user_id)
    finally:
        db.close()


async def save_timezone(guild_id, user_id, value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Choisis un fuseau valide, par exemple Europe/Brussels ou America/Montreal.") from exc
    db = await get_db_connection()
    try:
        async with db.cursor(aiomysql.DictCursor) as cursor:
            await _preferences(cursor, guild_id, user_id)
            await cursor.execute("UPDATE reminder_preferences SET timezone = %s WHERE guild_id = %s AND user_id = %s",
                                 (value, guild_id, user_id))
    finally:
        db.close()


async def _insert_reminder(cursor, reminder, preferences):
    await cursor.execute(
        "INSERT INTO guild_reminders "
        "(channel_id, due_at, message, category, mention_owner, recipient_ids, timezone, guild_id, user_id, "
        "personal_number, generation, parent_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (*_values(reminder), reminder.guild_id, reminder.user_id, preferences["next_number"],
         preferences["generation"], reminder.parent_id),
    )
    reminder_id = cursor.lastrowid
    await cursor.execute("UPDATE reminder_preferences SET next_number = next_number + 1 WHERE guild_id = %s AND user_id = %s",
                         (reminder.guild_id, reminder.user_id))
    return reminder_id


async def create_reminder(reminder: Reminder, *, expected_generation=None) -> int:
    reminder = validate_reminder(reminder)
    db = await get_db_connection()
    try:
        await db.begin()
        async with db.cursor(aiomysql.DictCursor) as cursor:
            preferences = await _preferences(cursor, reminder.guild_id, reminder.user_id, lock=True)
            if expected_generation is not None and preferences["generation"] != expected_generation:
                raise ValueError("Tes rappels ont été réinitialisés. Ouvre une nouvelle session.")
            reminder_id = await _insert_reminder(cursor, reminder, preferences)
        await db.commit()
        return reminder_id
    except BaseException:
        await db.rollback()
        raise
    finally:
        db.close()


async def list_reminders(guild_id: int, user_id: int, *, tab="active") -> list[Reminder]:
    statuses = {"active": "'pending', 'sending', 'failed'", "pending": "'pending', 'sending'",
                "failed": "'failed'", "sent": "'sent'"}[tab]
    db = await get_db_connection()
    try:
        async with db.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT * FROM guild_reminders WHERE guild_id = %s AND user_id = %s "
                f"AND status IN ({statuses}) ORDER BY due_at " + ("DESC" if tab == "sent" else "ASC") + ", id",
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


async def get_owned_reminder(reminder_id, guild_id, user_id, *, current_only=False):
    db = await get_db_connection()
    try:
        async with db.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT r.* FROM guild_reminders r JOIN reminder_preferences p "
                "ON p.guild_id = r.guild_id AND p.user_id = r.user_id "
                "WHERE r.id = %s AND r.guild_id = %s AND r.user_id = %s" +
                (" AND r.generation = p.generation" if current_only else ""), (reminder_id, guild_id, user_id),
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
                "category = %s, mention_owner = %s, recipient_ids = %s, timezone = %s, status = 'pending', "
                "attempts = 0, next_attempt_at = 0, claim_token = NULL, claimed_until = 0, "
                "last_error = NULL, finished_at = NULL, revision = revision + 1 "
                "WHERE id = %s AND guild_id = %s AND user_id = %s AND revision = %s "
                "AND status IN ('pending', 'failed')",
                (*_values(reminder), reminder.id, reminder.guild_id, reminder.user_id, reminder.revision),
            )
            return cursor.rowcount == 1
    finally:
        db.close()


async def delete_reminder(reminder_id: int, guild_id: int, user_id: int, *, revision=None) -> bool:
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "DELETE FROM guild_reminders WHERE id = %s AND guild_id = %s AND user_id = %s "
                "AND status IN ('pending', 'failed')" + (" AND revision = %s" if revision is not None else ""),
                (reminder_id, guild_id, user_id, *(() if revision is None else (revision,))),
            )
            return cursor.rowcount == 1
    finally:
        db.close()


async def reset_reminders(guild_id, user_id, generation, expected):
    """Cancel personal schedules atomically, preserving sent history and stable internal IDs."""
    db = await get_db_connection()
    try:
        await db.begin()
        async with db.cursor(aiomysql.DictCursor) as cursor:
            preferences = await _preferences(cursor, guild_id, user_id, lock=True)
            await cursor.execute(
                "SELECT id, revision, status FROM guild_reminders WHERE guild_id = %s AND user_id = %s "
                "AND status IN ('pending', 'sending', 'failed') ORDER BY id FOR UPDATE", (guild_id, user_id),
            )
            rows = await cursor.fetchall()
            if any(row["status"] == "sending" for row in rows):
                raise ValueError("Un de tes rappels est en cours d'envoi. Attends la fin de l'envoi avant de réinitialiser.")
            actual = tuple((row["id"], row["revision"], row["status"]) for row in rows)
            if preferences["generation"] != generation or actual != expected:
                raise ValueError("La liste a changé. Relance la remise à zéro pour vérifier les rappels concernés.")
            await cursor.execute("DELETE FROM guild_reminders WHERE guild_id = %s AND user_id = %s AND status IN ('pending', 'failed')",
                                 (guild_id, user_id))
            await cursor.execute("UPDATE reminder_preferences SET next_number = 1, generation = generation + 1 "
                                 "WHERE guild_id = %s AND user_id = %s", (guild_id, user_id))
        await db.commit()
        return len(rows)
    except BaseException:
        await db.rollback()
        raise
    finally:
        db.close()


async def snooze_reminder(source, due_at):
    db = await get_db_connection()
    try:
        await db.begin()
        async with db.cursor(aiomysql.DictCursor) as cursor:
            preferences = await _preferences(cursor, source.guild_id, source.user_id, lock=True)
            await cursor.execute("SELECT * FROM guild_reminders WHERE id = %s AND guild_id = %s AND user_id = %s FOR UPDATE",
                                 (source.id, source.guild_id, source.user_id))
            row = await cursor.fetchone()
            if not row or row["status"] != "sent" or row["generation"] != preferences["generation"]:
                raise ValueError("Ce rappel n'est plus disponible pour un report. Utilise `/reminder` sur le serveur d'origine.")
            await cursor.execute("SELECT id FROM guild_reminders WHERE parent_id = %s", (source.id,))
            if await cursor.fetchone():
                raise ValueError("Ce rappel a déjà été reporté. Retrouve le report dans `/reminder`.")
            fresh = _from_row(row)
            reminder_id = await _insert_reminder(cursor, replace(fresh, due_at=due_at, parent_id=source.id), preferences)
        await db.commit()
        return reminder_id
    except BaseException:
        await db.rollback()
        raise
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
