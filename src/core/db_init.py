from pathlib import Path

from src.core.schema_migrations import run_schema_migrations


# Column migrations: (table, column, ALTER statement)
_COLUMN_MIGRATIONS = [
    (
        "boutique_roles",
        "exclusif",
        "ALTER TABLE boutique_roles ADD COLUMN exclusif TINYINT(1) NOT NULL DEFAULT 0",
    ),
    (
        "users",
        "last_seen",
        "ALTER TABLE users ADD COLUMN last_seen TIMESTAMP NULL",
    ),
    (
        "rp_characters",
        "nax_balance",
        "ALTER TABLE rp_characters ADD COLUMN nax_balance BIGINT NOT NULL DEFAULT 0",
    ),
]


async def _run_migrations(db):
    cursor = await db.cursor()

    for table, column, sql in _COLUMN_MIGRATIONS:
        await cursor.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
            (table, column),
        )
        if (await cursor.fetchone())[0] == 0:
            await cursor.execute(sql)
            await db.commit()
            print(f"[MIGRATION] {table}.{column} ajouté")

    # Make discoveries global: remove guild_id if still present
    await cursor.execute(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'discoveries' AND COLUMN_NAME = 'guild_id'"
    )
    if (await cursor.fetchone())[0] > 0:
        await cursor.execute(
            "DELETE d1 FROM discoveries d1 "
            "INNER JOIN discoveries d2 "
            "ON d1.user_id = d2.user_id AND d1.egg_key = d2.egg_key "
            "AND d1.found_at > d2.found_at"
        )
        await cursor.execute("ALTER TABLE discoveries DROP PRIMARY KEY")
        await cursor.execute("ALTER TABLE discoveries DROP COLUMN guild_id")
        await cursor.execute("ALTER TABLE discoveries ADD PRIMARY KEY (user_id, egg_key)")
        await db.commit()
        print("[MIGRATION] discoveries rendu global (guild_id supprimé)")

    await cursor.close()



async def _migrate_economy_per_guild(db):
    from src.config import GUILD_IDS
    cursor = await db.cursor()
    for guild_id in GUILD_IDS:
        await cursor.execute(
            "INSERT IGNORE INTO guild_wallets (guild_id, user_id, balance) "
            "SELECT %s, user_id, balance FROM wallets",
            (guild_id,),
        )
        await cursor.execute(
            "INSERT INTO guild_boutique_roles (guild_id, role_id, prix, nom, description, exclusif) "
            "SELECT %s, role_id, prix, nom, description, exclusif FROM boutique_roles "
            "WHERE NOT EXISTS (SELECT 1 FROM guild_boutique_roles WHERE guild_id = %s)",
            (guild_id, guild_id),
        )
    await db.commit()
    await cursor.close()

async def init_db(db):
    model_dir = Path("src/model")
    if not model_dir.exists():
        print("[WARN] Dossier 'src/model/' introuvable.")
        return

    cursor = await db.cursor()
    for sql_file in sorted(model_dir.rglob("*.sql")):
        if sql_file.name.startswith("_"):
            continue
        try:
            await cursor.execute(sql_file.read_text(encoding="utf-8"))
            print(f"[SQL] {sql_file}")
        except Exception as e:
            print(f"[ERREUR SQL] {sql_file}: {e}")
    await cursor.close()

    await run_schema_migrations(db)
    await _run_migrations(db)
    await _migrate_economy_per_guild(db)
