"""Real versioned SQL migrations.

Each file in src/migrations/*.sql is executed exactly once and then
recorded in the `schema_migrations` table (filename = version).
Unlike the files in src/model/ (CREATE TABLE IF NOT EXISTS, replayed on
every startup), these files are never replayed once applied: this is the
mechanism to use for any future schema change (new table, ALTER, backfill...).
"""

from pathlib import Path
import logging

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path("src/migrations")


async def get_applied_versions(db) -> set[str]:
    cursor = await db.cursor()
    try:
        await cursor.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in await cursor.fetchall()}
    finally:
        await cursor.close()


async def run_schema_migrations(db) -> None:
    if not MIGRATIONS_DIR.exists():
        return

    applied = await get_applied_versions(db)
    cursor = await db.cursor()
    try:
        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = sql_file.stem
            if version in applied:
                continue
            statements = [s.strip() for s in sql_file.read_text(encoding="utf-8").split(";")]
            try:
                for statement in filter(None, statements):
                    await cursor.execute(statement)
                await cursor.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                    (version, sql_file.name),
                )
                await db.commit()
                logger.info("Applied migration %s", version)
            except Exception:
                await db.rollback()
                logger.exception("Migration failed: %s", version)
                raise
    finally:
        await cursor.close()
