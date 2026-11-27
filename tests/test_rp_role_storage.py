"""Exercise character role storage and constraints against the CI MySQL service."""

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import shutil
from uuid import uuid4

import aiomysql
import pytest

from src.core import schema_migrations
from src.core.db_init import init_db
from src.utils import rp_roles as store
from src.utils.rp_role_seed import AURUM_ROLES

PORT = os.getenv("REMINDER_TEST_DB_PORT") or os.getenv("TICKET_TEST_DB_PORT")
pytestmark = pytest.mark.skipif(not PORT, reason="Requires a disposable MySQL test database")

GUILD = 301
OTHER_GUILD = 302
OWNER = 42
ADMIN = store.Actor(10, True, frozenset())
VALIDATOR = store.Actor(11, False, frozenset({81}))
MEMBER = store.Actor(12, False, frozenset())
ROLE_IDS = {role_id for _, _, role_ids in AURUM_ROLES for role_id in role_ids}


@asynccontextmanager
async def database(monkeypatch):
    database_name = f"rp_roles_test_{uuid4().hex}"
    options = dict(host="127.0.0.1", port=int(PORT), user="root", password="", autocommit=True, charset="utf8mb4")
    server = await aiomysql.connect(**options)
    try:
        async with server.cursor() as cursor:
            await cursor.execute(f"CREATE DATABASE `{database_name}`")

        async def connect():
            return await aiomysql.connect(db=database_name, **options)

        monkeypatch.setattr(store, "get_db_connection", connect)
        yield connect
    finally:
        async with server.cursor() as cursor:
            await cursor.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
        server.close()


async def init(connect):
    db = await connect()
    try:
        await init_db(db)
    finally:
        db.close()


async def query(connect, sql, args=None):
    db = await connect()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(sql, args)
            return cursor.lastrowid, await cursor.fetchall()
    finally:
        db.close()


async def character(connect, guild_id, prefix, user_id=OWNER):
    character_id, _ = await query(
        connect, "INSERT INTO rp_characters (guild_id, user_id, name, prefix, image_url, nax_balance) "
        "VALUES (%s, %s, %s, %s, %s, 120)", (guild_id, user_id, "Néréide", prefix, "https://example.org/avatar.png"),
    )
    return character_id


async def revision(guild_id=GUILD):
    return (await store.settings(guild_id)).revision


async def create(name="Pays", mode="multiple", guild_id=GUILD):
    return await store.save_category(guild_id, ADMIN, await revision(guild_id), name=name, mode=mode, position=20)


async def assign(char_id, category_id, *ids, actor=ADMIN, guild_id=GUILD, available=(51, 52), owner_id=OWNER):
    await store.save_assignments(
        guild_id, actor, await revision(guild_id), owner_id, char_id, category_id, ids, available,
    )


async def assigned(char_id, category_id, guild_id=GUILD):
    grouped = await store.profile_roles(guild_id, char_id)
    return next(ids for category, ids in grouped.items() if category.id == category_id)


@pytest.mark.parametrize("upgrade", [False, True])
def test_mysql_init_and_upgrade_preserve_existing_character_and_retry(monkeypatch, tmp_path, upgrade):
    async def scenario():
        async with database(monkeypatch) as connect:
            if upgrade:
                for filename in Path("src/migrations").glob("*.sql"):
                    if filename.name < "0025":
                        shutil.copyfile(filename, tmp_path / filename.name)
                with monkeypatch.context() as previous:
                    previous.setattr(schema_migrations, "MIGRATIONS_DIR", tmp_path)
                    await init(connect)
                char_id = await character(connect, GUILD, "n:")
            await init(connect)
            assert (await store.settings(GUILD)) == store.Settings(0, False)
            assert await store.categories(GUILD) == []
            if not upgrade:
                char_id = await character(connect, GUILD, "n:")
            cat = await create()
            await store.link_roles(GUILD, ADMIN, await revision(), cat, {51}, {51})
            await assign(char_id, cat, 51)

            # MySQL may have applied the DDL before the migration journal commit.
            await query(connect, "DELETE FROM schema_migrations WHERE version = '0025_rp_character_roles'")
            await init(connect)
            assert await assigned(char_id, cat) == [51]
            _, rows = await query(connect, "SELECT name, prefix, nax_balance FROM rp_characters WHERE id = %s", (char_id,))
            assert rows == (("Néréide", "n:", 120),)
            _, rows = await query(connect, "SELECT COUNT(*) FROM schema_migrations WHERE version LIKE '0025%'")
            assert rows == ((1,),)

    asyncio.run(scenario())


def test_mysql_import_is_atomic_and_success_is_remembered_after_deletion(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as connect:
            await init(connect)
            with pytest.raises(store.RoleError, match="introuvables"):
                await store.import_initial(GUILD, ADMIN, 0, AURUM_ROLES, ROLE_IDS - {next(iter(ROLE_IDS))})
            assert await store.settings(GUILD) == store.Settings(0, False)
            assert await store.categories(GUILD) == []

            conflict = await create("Genre")
            with pytest.raises(store.RoleError, match="déjà utilisé"):
                await store.import_initial(GUILD, ADMIN, await revision(), AURUM_ROLES, ROLE_IDS)
            assert [cat.id for cat in await store.categories(GUILD)] == [conflict]
            assert not (await store.settings(GUILD)).imported
            await store.remove_category_or_link(GUILD, ADMIN, await revision(), conflict, 0)
            custom = await create("Métier")
            await store.change_validator_roles(GUILD, ADMIN, await revision(), [81], {81})

            current = await revision()
            results = await asyncio.gather(
                *(store.import_initial(GUILD, ADMIN, current, AURUM_ROLES, ROLE_IDS) for _ in range(2)),
                return_exceptions=True,
            )
            assert sum(result is None for result in results) == 1
            assert sum(isinstance(result, store.RoleError) for result in results) == 1
            seeded = {cat.name: cat for cat in await store.categories(GUILD) if cat.id != custom}
            assert len(seeded) == 6
            assert sum(len(ids) for _, _, ids in AURUM_ROLES) == len(ROLE_IDS) == 24
            for name, mode, ids in AURUM_ROLES:
                category, linked = await store.category_roles(GUILD, seeded[name].id)
                assert category.mode == mode
                assert linked == set(ids)
            assert await store.validator_roles(GUILD) == {81}
            assert await store.categories(OTHER_GUILD) == []
            await store.remove_category_or_link(GUILD, ADMIN, await revision(), seeded["Pays"].id, 0)

            await init(connect)
            with pytest.raises(store.RoleError, match="déjà été importé"):
                await store.import_initial(GUILD, ADMIN, await revision(), AURUM_ROLES, ROLE_IDS)
            assert (await store.settings(GUILD)).imported
            assert {cat.name for cat in await store.categories(GUILD)} == {"Métier", *seeded.keys()} - {"Pays"}
            _, audit = await query(connect, "SELECT actor_id, action FROM admin_audit WHERE action LIKE 'rproles.import%'")
            assert audit == ((ADMIN.id, "rproles.import: catégories=6"),)

    asyncio.run(scenario())


def test_mysql_assignments_isolate_owners_characters_and_servers(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as connect:
            await init(connect)
            first = await character(connect, GUILD, "n:")
            second = await character(connect, GUILD, "o:")
            foreign = await character(connect, OTHER_GUILD, "n:")
            local_cat = await create("Race", mode="single")
            other_cat = await create("Race", mode="single", guild_id=OTHER_GUILD)
            await store.link_roles(GUILD, ADMIN, await revision(), local_cat, {51, 52}, {51, 52})
            await store.link_roles(OTHER_GUILD, ADMIN, await revision(OTHER_GUILD), other_cat, {51}, {51})
            another_category = await create("Genre")
            with pytest.raises(store.RoleError, match="déjà lié"):
                await store.link_roles(GUILD, ADMIN, await revision(), another_category, {51, 53}, {51, 53})
            assert (await store.category_roles(GUILD, another_category))[1] == set()
            with pytest.raises(store.RoleError, match="introuvables"):
                await store.link_roles(GUILD, ADMIN, await revision(), another_category, {53}, set())
            await assign(first, local_cat, 51)
            await assign(second, local_cat, 52)
            await assign(foreign, other_cat, 51, guild_id=OTHER_GUILD)

            with pytest.raises(store.RoleError, match="un seul rôle"):
                await assign(first, local_cat, 51, 52)
            with pytest.raises(store.RoleError, match="pas lié|plus lié"):
                await assign(first, local_cat, 53, available={53})
            with pytest.raises(store.RoleError, match="personnage"):
                await assign(foreign, local_cat, 51)
            with pytest.raises(store.RoleError, match="personnage"):
                await assign(first, local_cat, 51, owner_id=44)
            for guild, char_id, cat, role, mode in (
                (GUILD, first, local_cat, 52, "single"),      # second role in a single category
                (GUILD, first, local_cat, 52, "multiple"),    # forged mode
                (GUILD, foreign, local_cat, 51, "single"),   # foreign character
                (OTHER_GUILD, foreign, local_cat, 51, "single"),  # foreign category
            ):
                with pytest.raises(aiomysql.IntegrityError):
                    await query(
                        connect, "INSERT INTO rp_character_roles (guild_id, character_id, category_id, role_id, mode) "
                        "VALUES (%s, %s, %s, %s, %s)", (guild, char_id, cat, role, mode),
                    )

            await query(connect, "UPDATE rp_characters SET name = 'Renommé', prefix = 'r:' WHERE id = %s", (first,))
            renamed = {char.id: char for char in await store.list_characters(GUILD, OWNER)}[first]
            assert (renamed.name, renamed.prefix) == ("Renommé", "r:")
            assert await assigned(first, local_cat) == [51]
            await query(connect, "DELETE FROM rp_characters WHERE id = %s", (first,))
            assert await assigned(first, local_cat) == []
            assert await assigned(second, local_cat) == [52]
            assert await assigned(foreign, other_cat, OTHER_GUILD) == [51]

    asyncio.run(scenario())


def test_mysql_mode_conversion_unlink_and_category_delete_can_be_retried(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as connect:
            await init(connect)
            first = await character(connect, GUILD, "n:")
            second = await character(connect, GUILD, "o:")
            cat = await create()
            other = await create("Race", mode="single")
            await store.link_roles(GUILD, ADMIN, await revision(), cat, {51, 52}, {51, 52})
            await store.link_roles(GUILD, ADMIN, await revision(), other, {53}, {53})
            await assign(first, cat, 51, 52)
            await assign(second, cat, 52)
            await assign(second, other, 53, available={53})
            with pytest.raises(store.RoleError, match="plusieurs rôles"):
                await store.save_category(GUILD, ADMIN, await revision(), name="Origine", position=3, mode="single",
                                          category_id=cat)
            assert await assigned(first, cat) == [51, 52]

            # An unavailable Discord role can be removed, but cannot be assigned again.
            await assign(first, cat, 52, available=set())
            with pytest.raises(store.RoleError, match="introuvables"):
                await assign(first, cat, 51, 52, available={52})
            await store.save_category(GUILD, ADMIN, await revision(), name="Origine", position=3, mode="single",
                                      category_id=cat)
            assert (await store.categories(GUILD))[0].mode == "single"
            assert (await store.categories(GUILD))[0].name == "Origine"
            assert await assigned(first, cat) == [52]
            count = await store.affected_characters(GUILD, cat, 52)
            assert count == 2
            original_revision = await revision()
            await query(connect, "DELETE FROM rp_characters WHERE id = %s", (first,))
            with pytest.raises(store.RoleError, match="nombre de personnages"):
                await store.remove_category_or_link(GUILD, ADMIN, original_revision, cat, count, role_id=52)
            await store.remove_category_or_link(GUILD, ADMIN, original_revision, cat, 1, role_id=52)
            assert await assigned(second, cat) == []
            await assign(second, cat, 51)
            assert await store.affected_characters(GUILD, cat) == 1
            await store.remove_category_or_link(GUILD, ADMIN, await revision(), cat, 1)
            assert set(await store.profile_roles(GUILD, second)) == {store.Category(other, "Race", 20, "single")}
            assert await assigned(second, other) == [53]

    asyncio.run(scenario())


def test_mysql_transaction_rechecks_validators_rejects_stale_and_audits_atomic_writes(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as connect:
            await init(connect)
            char_id = await character(connect, GUILD, "n:")
            category = await create()
            await store.link_roles(GUILD, ADMIN, await revision(), category, {51, 52}, {51, 52})
            with pytest.raises(store.RoleError, match="accès"):
                await assign(char_id, category, 51, actor=MEMBER)
            with pytest.raises(store.RoleError, match="everyone"):
                await store.change_validator_roles(GUILD, ADMIN, await revision(), [GUILD], {GUILD})
            await store.change_validator_roles(GUILD, ADMIN, await revision(), [81], {81})
            assert await store.can_manage(GUILD, VALIDATOR)
            assert not await store.can_manage(OTHER_GUILD, VALIDATOR)
            with pytest.raises(store.RoleError, match="accès"):
                await store.save_category(GUILD, VALIDATOR, await revision(), name="Staff", position=0, mode="multiple")

            old = await revision()
            results = await asyncio.gather(
                *(store.save_assignments(GUILD, VALIDATOR, old, OWNER, char_id, category, ids, {51, 52})
                  for ids in ({51}, {52})),
                return_exceptions=True,
            )
            assert results.count(None) == 1
            assert any(isinstance(result, store.RoleError) and str(result) == store.STALE for result in results)
            current = await assigned(char_id, category)
            assert current in ([51], [52])
            _, audit = await query(connect, "SELECT actor_id, action FROM admin_audit WHERE action LIKE 'rproles.assign:%'")
            assert audit == ((VALIDATOR.id, f"rproles.assign: p={char_id} c={category} r={current[0]}"),)
            with monkeypatch.context() as failing:
                async def fail_audit(*args):
                    raise RuntimeError("Audit indisponible")

                failing.setattr(store, "write_admin_actions", fail_audit)
                with pytest.raises(RuntimeError, match="Audit"):
                    await assign(char_id, category)
            assert await assigned(char_id, category) == current
            assert await revision() == old + 1

            await store.change_validator_roles(GUILD, ADMIN, await revision(), [81], {}, remove=True)
            with pytest.raises(store.RoleError, match="accès"):
                await assign(char_id, category, actor=VALIDATOR)
            await assign(char_id, category)
            assert await assigned(char_id, category) == []
            _, audit = await query(connect, "SELECT actor_id, action FROM admin_audit WHERE action LIKE 'rproles.remove:%'")
            assert audit == ((ADMIN.id, f"rproles.remove: p={char_id} c={category} r={current[0]}"),)

    asyncio.run(scenario())
