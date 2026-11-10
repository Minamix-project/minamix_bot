"""Guild-scoped ticket persistence and serialized, transactional mutations."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
import json
import logging

import aiomysql

from src.utils.db import get_db_connection


CATEGORIES = {
    "general": "Support général",
    "rp": "Problème RP",
    "shop": "Boutique",
    "report": "Signalement",
    "application": "Candidature",
    "staff": "Demande au staff",
}
PART_SIZE = 256 * 1024
logger = logging.getLogger(__name__)


class TicketError(Exception):
    """An actionable ticket error whose text can be shown to the member."""


@dataclass
class PanelDraft:
    id: int | None = None
    name: str = "Support"
    title: str | None = None
    text: str | None = None
    staff_role_ids: tuple[int, ...] = ()
    category_id: int | None = None
    transcript_channel_id: int | None = None
    channel_id: int | None = None
    version: int = 0

    @classmethod
    def from_panel(cls, panel):
        return cls(
            id=panel["id"],
            name=panel["name"],
            title=panel["title"],
            text=panel["description"],
            staff_role_ids=tuple(panel["staff_role_ids"]),
            category_id=panel["category_id"],
            transcript_channel_id=panel["transcript_channel_id"],
            channel_id=panel["channel_id"],
            version=panel["version"],
        )


@dataclass
class Ticket:
    id: int
    guild_id: int
    channel_id: int
    creator_id: int
    category: str
    staff_role_ids: tuple[int, ...]
    transcript_channel_id: int | None
    subject_id: int | None
    status: str
    created_at: datetime
    closed_at: datetime | None
    closed_by: int | None
    close_reason: str | None
    saved_overwrites: str | None
    active_creator: int | None = None
    ticket_number: int | None = None
    panel_id: int | None = None

    @classmethod
    def from_row(cls, row):
        return cls(**{**row, "staff_role_ids": tuple(json.loads(row["staff_role_ids"]))})

    @property
    def reference(self):
        return f"{self.ticket_number if self.ticket_number is not None else self.id:04d}"


class TicketSession:
    def __init__(self, db, guild_id):
        self.db = db
        self.guild_id = guild_id

    async def execute(self, sql, args=None):
        async with self.db.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return cursor.lastrowid

    async def rows(self, sql, args=None):
        async with self.db.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return await cursor.fetchall()

    @staticmethod
    def panel_row(row):
        return {**row, "staff_role_ids": tuple(json.loads(row["staff_role_ids"]))}

    async def panels(self):
        rows = await self.rows("SELECT * FROM ticket_panels WHERE guild_id = %s ORDER BY id", (self.guild_id,))
        return [self.panel_row(row) for row in rows]

    async def panel(self, panel_id):
        rows = await self.rows("SELECT * FROM ticket_panels WHERE guild_id = %s AND id = %s", (self.guild_id, panel_id))
        return self.panel_row(rows[0]) if rows else None

    async def panel_for_message(self, channel_id, message_id):
        rows = await self.rows(
            "SELECT * FROM ticket_panels WHERE guild_id = %s AND channel_id = %s AND message_id = %s",
            (self.guild_id, channel_id, message_id),
        )
        return self.panel_row(rows[0]) if rows else None

    async def save_panel(
        self,
        channel_id,
        message_id,
        category_id,
        staff_role_ids,
        transcript_channel_id,
        *,
        panel_id=None,
        name="Support",
        title=None,
        text=None,
    ):
        values = (
            channel_id,
            message_id,
            category_id,
            json.dumps(list(staff_role_ids)),
            transcript_channel_id,
            name,
            title,
            text,
        )
        if panel_id is None:
            return await self.execute(
                "INSERT INTO ticket_panels (channel_id, message_id, category_id, staff_role_ids, transcript_channel_id, "
                "name, title, description, guild_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (*values, self.guild_id),
            )
        await self.execute(
            "UPDATE ticket_panels SET channel_id = %s, message_id = %s, category_id = %s, staff_role_ids = %s, "
            "transcript_channel_id = %s, name = %s, title = %s, description = %s, version = version + 1 "
            "WHERE guild_id = %s AND id = %s",
            (*values, self.guild_id, panel_id),
        )
        return panel_id

    async def delete_panel(self, panel_id):
        await self.execute("DELETE FROM ticket_panels WHERE guild_id = %s AND id = %s", (self.guild_id, panel_id))

    async def get(self, channel_id):
        rows = await self.rows(
            "SELECT * FROM tickets WHERE guild_id = %s AND channel_id = %s",
            (self.guild_id, channel_id),
        )
        return Ticket.from_row(rows[0]) if rows else None

    async def active(self, creator_id):
        rows = await self.rows(
            "SELECT * FROM tickets WHERE guild_id = %s AND active_creator = %s",
            (self.guild_id, creator_id),
        )
        return Ticket.from_row(rows[0]) if rows else None

    async def next_number(self):
        await self.execute(
            "INSERT INTO ticket_sequences (guild_id) VALUES (%s) ON DUPLICATE KEY UPDATE guild_id = %s",
            (self.guild_id, self.guild_id),
        )
        rows = await self.rows(
            "SELECT next_number FROM ticket_sequences WHERE guild_id = %s FOR UPDATE", (self.guild_id,)
        )
        number = rows[0]["next_number"]
        await self.execute(
            "UPDATE ticket_sequences SET next_number = next_number + 1 WHERE guild_id = %s", (self.guild_id,)
        )
        return number

    async def all(self):
        rows = await self.rows("SELECT * FROM tickets WHERE guild_id = %s ORDER BY id", (self.guild_id,))
        return [Ticket.from_row(row) for row in rows]

    async def purge(self):
        # Use the history subsystem's state lock to keep its counters consistent.
        await self.rows(
            "SELECT guild_id FROM guild_message_history_state WHERE guild_id = %s FOR UPDATE", (self.guild_id,)
        )
        await self.execute(
            "DELETE h FROM guild_message_history h JOIN tickets t ON t.guild_id = h.guild_id AND t.channel_id = h.channel_id "
            "WHERE t.guild_id = %s",
            (self.guild_id,),
        )
        await self.execute(
            "UPDATE guild_message_history_state SET entry_count = "
            "(SELECT COUNT(*) FROM guild_message_history WHERE guild_id = %s), generation = generation + 1 WHERE guild_id = %s",
            (self.guild_id, self.guild_id),
        )
        # Events, staff participation and transcript parts are removed by foreign-key cascades.
        await self.execute("DELETE FROM tickets WHERE guild_id = %s", (self.guild_id,))
        await self.execute("DELETE FROM ticket_sequences WHERE guild_id = %s", (self.guild_id,))
        await self.execute(
            "DELETE FROM admin_audit WHERE guild_id = %s AND action LIKE %s", (self.guild_id, "ticket.%")
        )

    async def create(self, channel_id, creator_id, category, panel, *, number=None):
        if number is None:
            number = await self.next_number()
        return await self.execute(
            "INSERT INTO tickets (guild_id, channel_id, creator_id, category, staff_role_ids, transcript_channel_id, ticket_number, panel_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP())",
            (
                self.guild_id,
                channel_id,
                creator_id,
                category,
                json.dumps(list(panel["staff_role_ids"])),
                panel["transcript_channel_id"],
                number,
                panel.get("id"),
            ),
        )

    async def event(self, ticket, actor_id, action, detail=None, *, staff=False):
        await self.execute(
            "INSERT INTO ticket_events (ticket_id, actor_id, action, detail, created_at) "
            "VALUES (%s, %s, %s, %s, UTC_TIMESTAMP())",
            (ticket.id, actor_id, action, detail),
        )
        if staff:
            await self.execute(
                "INSERT INTO ticket_staff (ticket_id, user_id, first_seen_at) VALUES (%s, %s, UTC_TIMESTAMP()) "
                "ON DUPLICATE KEY UPDATE user_id = ticket_staff.user_id",
                (ticket.id, actor_id),
            )
        await self.execute(
            "INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)",
            (self.guild_id, actor_id, f"ticket.{action}: #{ticket.reference} channel={ticket.channel_id}"),
        )

    async def close(self, ticket, actor_id, reason, overwrites):
        await self.execute(
            "UPDATE tickets SET status = 'closed', closed_at = UTC_TIMESTAMP(), closed_by = %s, "
            "close_reason = %s, saved_overwrites = %s WHERE id = %s AND guild_id = %s",
            (actor_id, reason, json.dumps(overwrites), ticket.id, self.guild_id),
        )

    async def reopen(self, ticket):
        await self.execute(
            "UPDATE tickets SET status = 'open', closed_at = NULL, closed_by = NULL, "
            "close_reason = NULL, saved_overwrites = NULL WHERE id = %s AND guild_id = %s",
            (ticket.id, self.guild_id),
        )

    async def link(self, ticket, subject_id):
        await self.execute(
            "UPDATE tickets SET subject_id = %s WHERE id = %s AND guild_id = %s", (subject_id, ticket.id, self.guild_id)
        )

    async def save_transcript(self, ticket, actor_id, content):
        transcript_id = await self.execute(
            "INSERT INTO ticket_transcripts (ticket_id, created_by, created_at) VALUES (%s, %s, UTC_TIMESTAMP())",
            (ticket.id, actor_id),
        )
        # Hex parameters avoid driver-specific byte escaping and preserve arbitrary UTF-8 chunk boundaries.
        for index, offset in enumerate(range(0, len(content), PART_SIZE)):
            await self.execute(
                "INSERT INTO ticket_transcript_parts (transcript_id, part_number, content) VALUES (%s, %s, UNHEX(%s))",
                (transcript_id, index, content[offset : offset + PART_SIZE].hex()),
            )
        return transcript_id

    async def latest_transcript(self, ticket):
        rows = await self.rows(
            "SELECT p.content FROM ticket_transcript_parts p JOIN ticket_transcripts t ON t.id = p.transcript_id "
            "WHERE t.ticket_id = %s AND t.id = (SELECT MAX(id) FROM ticket_transcripts WHERE ticket_id = %s) "
            "ORDER BY p.part_number",
            (ticket.id, ticket.id),
        )
        return b"".join(row["content"] for row in rows) if rows else None

    async def history(self, ticket):
        staff = await self.rows(
            "SELECT user_id FROM ticket_staff WHERE ticket_id = %s ORDER BY first_seen_at", (ticket.id,)
        )
        events = await self.rows("SELECT * FROM ticket_events WHERE ticket_id = %s ORDER BY id", (ticket.id,))
        return staff, events


@asynccontextmanager
async def ticket_session(guild_id):
    """Coordinate Discord mutations across processes and commit their metadata together."""
    db = await get_db_connection()
    lock_name = f"aurum:tickets:{guild_id}"
    locked = False
    try:
        async with db.cursor() as cursor:
            await cursor.execute("SELECT GET_LOCK(%s, 0)", (lock_name,))
            locked = (await cursor.fetchone())[0] == 1
        if not locked:
            raise TicketError("Une opération sur les tickets est en cours. Réessaie dans quelques secondes.")
        await db.begin()
        yield TicketSession(db, guild_id)
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    finally:
        try:
            if locked:
                async with db.cursor() as cursor:
                    await cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
        except Exception:
            # Cleanup failure must not undo a Discord action after a successful commit.
            logger.exception("Could not release ticket lock guild=%s", guild_id)
            try:
                await db.ensure_closed()
            except Exception:
                logger.exception("Could not discard ticket connection guild=%s", guild_id)
        finally:
            db.close()


async def record_staff_message(guild_id, channel_id, member):
    """Record staff participation without retaining message content."""
    from src.utils.permissions import is_admin

    role_ids = {role.id for role in member.roles}
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "SELECT id, staff_role_ids FROM tickets WHERE guild_id = %s AND channel_id = %s AND status = 'open'",
                (guild_id, channel_id),
            )
            row = await cursor.fetchone()
            if row and (is_admin(member) or role_ids.intersection(json.loads(row[1]))):
                await cursor.execute(
                    "INSERT INTO ticket_staff (ticket_id, user_id, first_seen_at) VALUES (%s, %s, UTC_TIMESTAMP()) "
                    "ON DUPLICATE KEY UPDATE user_id = ticket_staff.user_id",
                    (row[0], member.id),
                )
    finally:
        db.close()
