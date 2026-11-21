"""Guild-scoped ticket persistence and serialized, transactional mutations."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
import json
import logging

import aiomysql

from src.utils.db import get_db_connection


@dataclass(frozen=True)
class TicketCategory:
    label: str
    emoji: str
    description: str
    welcome: str


CATEGORY_OPTIONS = {
    "partnerships": TicketCategory(
        "Partenariats", "🔗", "Pour faire une demande de partenariats",
        "Présente ton projet et précise le partenariat que tu souhaites proposer.",
    ),
    "character_validation": TicketCategory(
        "Validation de Fiche", "✅", "Pour faire valider votre fiche de personnage ou autre",
        "Envoie ta fiche de personnage ou le document à faire valider par le staff.",
    ),
    "report": TicketCategory(
        "Plaintes", "⛔", "Pour porter plainte contre un autre membre du serveur",
        "Décris la situation et indique le membre concerné. Ajoute des preuves si tu en as.",
    ),
    "general": TicketCategory(
        "Besoin d'aide", "🆘", "Si vous avez besoin de l'aide du Staff",
        "Explique-nous ce dont tu as besoin pour que le staff puisse t'aider.",
    ),
    "other": TicketCategory(
        "Autres", "🤔", "Pour tout autre chose qui requiert l'attention du staff",
        "Présente ta demande et donne les détails utiles au staff.",
    ),
    "bot": TicketCategory(
        "Bot", "🤖", "Pour toute question ou tout problème concernant le bot",
        "Décris ton problème ou ta question concernant le bot. "
        "Précise la commande utilisée et joins une capture si possible.",
    ),
}
CATEGORIES = {key: option.label for key, option in CATEGORY_OPTIONS.items()}
LEGACY_CATEGORIES = {"rp": "Problème RP", "shop": "Boutique", "application": "Candidature", "staff": "Demande au staff"}
MAX_CATEGORIES = 25
PART_SIZE = 256 * 1024
logger = logging.getLogger(__name__)


def category_label(category):
    return CATEGORIES.get(category, LEGACY_CATEGORIES.get(category, "Catégorie inconnue"))


class TicketError(Exception):
    """An actionable ticket error whose text can be shown to the member."""


@dataclass
class CategoryDraft:
    category_key: str
    name: str
    emoji: str
    description: str
    welcome: str
    staff_role_ids: tuple[int, ...] = ()
    version: int = 1
    claim_enabled: bool = True

    @classmethod
    def from_category(cls, category):
        return cls(**{key: category[key] for key in cls.__dataclass_fields__})


@dataclass
class PanelDraft:
    id: int | None = None
    name: str = "Support"
    title: str | None = None
    text: str | None = None
    category_id: int | None = None
    transcript_channel_id: int | None = None
    logs_channel_id: int | None = None
    channel_id: int | None = None
    version: int = 0

    @classmethod
    def from_panel(cls, panel):
        return cls(
            id=panel["id"],
            name=panel["name"],
            title=panel["title"],
            text=panel["description"],
            category_id=panel["category_id"],
            transcript_channel_id=panel["transcript_channel_id"],
            logs_channel_id=panel["logs_channel_id"],
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
    logs_channel_id: int | None = None
    category_version: int = 0
    welcome_message_id: int | None = None
    category_name: str | None = None
    claim_enabled: bool = True
    claimed_by: int | None = None
    claimed_at: datetime | None = None
    claim_base_name: str | None = None
    channel_base_name: str | None = None
    claim_emoji: str = "🟢"
    admin_role_ids: tuple[int, ...] = ()

    @classmethod
    def from_row(cls, row):
        return cls(**{**row, "staff_role_ids": tuple(json.loads(row["staff_role_ids"])),
                      "admin_role_ids": tuple(json.loads(row.get("admin_role_ids") or "[]"))})

    @property
    def reference(self):
        return f"{self.ticket_number if self.ticket_number is not None else self.id:04d}"

    @property
    def label(self):
        return self.category_name or category_label(self.category)


class TicketSession:
    def __init__(self, db, guild_id):
        self.db = db
        self.guild_id = guild_id
        self.categories_ready = False

    async def execute(self, sql, args=None):
        async with self.db.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return cursor.lastrowid

    async def rows(self, sql, args=None):
        async with self.db.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return await cursor.fetchall()

    async def ensure_categories(self):
        if self.categories_ready:
            return
        for position, (key, option) in enumerate(CATEGORY_OPTIONS.items()):
            await self.execute(
                "INSERT INTO ticket_categories "
                "(guild_id, category_key, name, emoji, description, welcome, staff_role_ids, position) "
                "VALUES (%s, %s, %s, %s, %s, %s, JSON_ARRAY(), %s) "
                "ON DUPLICATE KEY UPDATE category_key = ticket_categories.category_key",
                (self.guild_id, key, option.label, option.emoji, option.description, option.welcome, position),
            )
        self.categories_ready = True

    async def categories(self):
        await self.ensure_categories()
        rows = await self.rows(
            "SELECT * FROM ticket_categories WHERE guild_id = %s AND is_active = 1 ORDER BY position, category_key",
            (self.guild_id,),
        )
        return [{**row, "staff_role_ids": tuple(json.loads(row["staff_role_ids"]))} for row in rows]

    async def category(self, key, *, include_inactive=False):
        if include_inactive:
            await self.ensure_categories()
            rows = await self.rows(
                "SELECT * FROM ticket_categories WHERE guild_id = %s AND category_key = %s", (self.guild_id, key),
            )
            return {**rows[0], "staff_role_ids": tuple(json.loads(rows[0]["staff_role_ids"]))} if rows else None
        return next((category for category in await self.categories() if category["category_key"] == key), None)

    async def save_category(self, draft):
        await self.execute(
            "UPDATE ticket_categories SET name = %s, emoji = %s, description = %s, welcome = %s, "
            "staff_role_ids = %s, claim_enabled = %s, version = version + 1 WHERE guild_id = %s AND category_key = %s",
            (draft.name, draft.emoji, draft.description, draft.welcome, json.dumps(list(draft.staff_role_ids)),
             draft.claim_enabled, self.guild_id, draft.category_key),
        )

    async def create_category(self, key, draft):
        rows = await self.rows(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next_position FROM ticket_categories WHERE guild_id = %s",
            (self.guild_id,),
        )
        await self.execute(
            "INSERT INTO ticket_categories "
            "(guild_id, category_key, name, emoji, description, welcome, staff_role_ids, position, claim_enabled) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (self.guild_id, key, draft.name, draft.emoji, draft.description, draft.welcome,
             json.dumps(list(draft.staff_role_ids)), rows[0]["next_position"], draft.claim_enabled),
        )

    async def delete_category(self, key):
        # Retain category metadata for historical tickets and prevent default reseeding.
        await self.execute(
            "UPDATE ticket_categories SET is_active = 0, version = version + 1 "
            "WHERE guild_id = %s AND category_key = %s AND is_active = 1",
            (self.guild_id, key),
        )

    async def ticket_rows(self, condition, args):
        rows = await self.rows(
            "SELECT t.*, c.name AS category_name, COALESCE(c.claim_enabled, 1) AS claim_enabled, "
            "COALESCE(p.emoji, '🟢') AS claim_emoji "
            "FROM tickets t LEFT JOIN ticket_categories c "
            "ON c.guild_id = t.guild_id AND c.category_key = t.category "
            "LEFT JOIN ticket_staff_preferences p ON p.guild_id = t.guild_id AND p.user_id = t.claimed_by "
            "WHERE " + condition, args,
        )
        return [Ticket.from_row(row) for row in rows]

    async def for_claimant(self, user_id):
        return await self.ticket_rows("t.guild_id = %s AND t.claimed_by = %s ORDER BY t.id", (self.guild_id, user_id))

    async def set_staff_emoji(self, user_id, emoji):
        if emoji is None:
            await self.execute("DELETE FROM ticket_staff_preferences WHERE guild_id = %s AND user_id = %s",
                               (self.guild_id, user_id))
        else:
            await self.execute(
                "INSERT INTO ticket_staff_preferences (guild_id, user_id, emoji) VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE emoji = %s", (self.guild_id, user_id, emoji, emoji),
            )

    async def set_channel_base_name(self, ticket, name):
        await self.execute("UPDATE tickets SET channel_base_name = %s WHERE guild_id = %s AND id = %s",
                           (name, self.guild_id, ticket.id))

    async def panels(self):
        rows = await self.rows("SELECT * FROM ticket_panels WHERE guild_id = %s ORDER BY id", (self.guild_id,))
        return list(rows)

    async def panel(self, panel_id):
        rows = await self.rows("SELECT * FROM ticket_panels WHERE guild_id = %s AND id = %s", (self.guild_id, panel_id))
        return rows[0] if rows else None

    async def panel_for_message(self, channel_id, message_id):
        rows = await self.rows(
            "SELECT * FROM ticket_panels WHERE guild_id = %s AND channel_id = %s AND message_id = %s",
            (self.guild_id, channel_id, message_id),
        )
        return rows[0] if rows else None

    async def save_panel(
        self,
        channel_id,
        message_id,
        category_id,
        transcript_channel_id,
        *,
        logs_channel_id=None,
        panel_id=None,
        name="Support",
        title=None,
        text=None,
    ):
        values = (
            channel_id,
            message_id,
            category_id,
            transcript_channel_id,
            logs_channel_id,
            name,
            title,
            text,
        )
        if panel_id is None:
            return await self.execute(
                "INSERT INTO ticket_panels (channel_id, message_id, category_id, transcript_channel_id, "
                "logs_channel_id, name, title, description, guild_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (*values, self.guild_id),
            )
        await self.execute(
            "UPDATE ticket_panels SET channel_id = %s, message_id = %s, category_id = %s, "
            "transcript_channel_id = %s, logs_channel_id = %s, name = %s, title = %s, description = %s, version = version + 1 "
            "WHERE guild_id = %s AND id = %s",
            (*values, self.guild_id, panel_id),
        )
        return panel_id

    async def delete_panel(self, panel_id):
        await self.execute("DELETE FROM ticket_panels WHERE guild_id = %s AND id = %s", (self.guild_id, panel_id))

    async def get(self, channel_id):
        rows = await self.ticket_rows(
            "t.guild_id = %s AND t.channel_id = %s",
            (self.guild_id, channel_id),
        )
        return rows[0] if rows else None

    async def active(self, creator_id, category):
        rows = await self.ticket_rows(
            "t.guild_id = %s AND t.active_creator = %s AND t.category = %s",
            (self.guild_id, creator_id, category),
        )
        return rows[0] if rows else None

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
        return await self.ticket_rows("t.guild_id = %s ORDER BY t.id", (self.guild_id,))

    async def for_category(self, key):
        return await self.ticket_rows(
            "t.guild_id = %s AND t.category = %s ORDER BY t.id", (self.guild_id, key),
        )

    async def update_category(self, ticket, category, saved_overwrites, welcome_message_id, *, admin_role_ids=()):
        await self.execute(
            "UPDATE tickets SET staff_role_ids = %s, saved_overwrites = %s, category_version = %s, "
            "welcome_message_id = %s, admin_role_ids = %s WHERE guild_id = %s AND id = %s",
            (json.dumps(list(category["staff_role_ids"])), saved_overwrites, category["version"],
             welcome_message_id, json.dumps(list(admin_role_ids)), self.guild_id, ticket.id),
        )

    async def set_welcome_message(self, ticket, message_id):
        await self.execute(
            "UPDATE tickets SET welcome_message_id = %s WHERE guild_id = %s AND id = %s",
            (message_id, self.guild_id, ticket.id),
        )

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

    async def create(self, channel_id, creator_id, category, panel, *, number=None, staff_role_ids=(), category_version=0,
                     channel_base_name=None, admin_role_ids=()):
        if number is None:
            number = await self.next_number()
        return await self.execute(
            "INSERT INTO tickets (guild_id, channel_id, creator_id, category, staff_role_ids, transcript_channel_id, "
            "logs_channel_id, ticket_number, panel_id, category_version, channel_base_name, admin_role_ids, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP())",
            (
                self.guild_id,
                channel_id,
                creator_id,
                category,
                json.dumps(list(staff_role_ids)),
                panel["transcript_channel_id"],
                panel.get("logs_channel_id"),
                number,
                panel.get("id"),
                category_version,
                channel_base_name,
                json.dumps(list(admin_role_ids)),
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

    async def claim(self, ticket, actor_id, base_name):
        async with self.db.cursor() as cursor:
            await cursor.execute(
                "UPDATE tickets SET claimed_by = %s, claimed_at = UTC_TIMESTAMP(), claim_base_name = %s "
                "WHERE guild_id = %s AND id = %s AND claimed_by IS NULL AND status = 'open'",
                (actor_id, base_name, self.guild_id, ticket.id),
            )
            if cursor.rowcount != 1:
                raise TicketError("Ce ticket est déjà pris en charge ou a été fermé. Actualise le ticket.")

    async def release(self, ticket):
        async with self.db.cursor() as cursor:
            await cursor.execute(
                "UPDATE tickets SET claimed_by = NULL, claimed_at = NULL, claim_base_name = NULL "
                "WHERE guild_id = %s AND id = %s AND claimed_by = %s",
                (self.guild_id, ticket.id, ticket.claimed_by),
            )
            if cursor.rowcount != 1:
                raise TicketError("Le responsable de ce ticket a changé. Actualise le ticket avant de le libérer.")

    async def set_claim_base_name(self, ticket, name):
        await self.execute(
            "UPDATE tickets SET claim_base_name = %s WHERE guild_id = %s AND id = %s",
            (name, self.guild_id, ticket.id),
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

    async def delete(self, ticket):
        # Retain events and transcripts; only a full purge removes archives.
        await self.execute("UPDATE tickets SET status = 'deleted' WHERE id = %s AND guild_id = %s",
                           (ticket.id, self.guild_id))

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
                "SELECT id, staff_role_ids FROM tickets WHERE guild_id = %s AND channel_id = %s AND status IN ('open', 'closed')",
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
