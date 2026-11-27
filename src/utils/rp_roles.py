"""Storage and write rules for Discord role references attached to RP characters."""

from collections.abc import Collection
from contextlib import asynccontextmanager
from dataclasses import dataclass

from aiomysql import IntegrityError

from src.utils.audit import write_admin_actions
from src.utils.db import get_db_connection
from src.utils.permissions import is_admin

STALE = "La configuration ou les attributions ont changé. Actualise le menu puis réessaie."
DENIED = "Tu n'as plus accès à cette action sur les rôles RP."
MODE_CONFLICT = (
    "Des personnages ont plusieurs rôles dans cette catégorie. "
    "Ramène chaque personnage à un rôle maximum avant de choisir le mode unique."
)
MODES = {"single": "Unique", "multiple": "Multiple"}


class RoleError(ValueError):
    """An expected rejection that can be shown to the user."""


@dataclass(frozen=True)
class Actor:
    id: int
    admin: bool
    role_ids: frozenset[int]

    @classmethod
    def from_member(cls, member):
        return cls(member.id, is_admin(member), frozenset(role.id for role in member.roles))


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    position: int
    mode: str


@dataclass(frozen=True)
class Settings:
    revision: int
    imported: bool


@dataclass(frozen=True)
class Character:
    id: int
    name: str
    prefix: str
    image_url: str


@asynccontextmanager
async def _cursor():
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            yield cursor
    finally:
        db.close()


async def _role_ids(cursor, guild_id):
    await cursor.execute("SELECT role_id FROM rp_role_validators WHERE guild_id = %s", (guild_id,))
    return frozenset(row[0] for row in await cursor.fetchall())


async def validator_roles(guild_id):
    async with _cursor() as cursor:
        return await _role_ids(cursor, guild_id)


async def can_manage(guild_id, actor):
    return actor.admin or bool(actor.role_ids & await validator_roles(guild_id))


async def settings(guild_id):
    async with _cursor() as cursor:
        await cursor.execute("SELECT revision, imported FROM rp_role_settings WHERE guild_id = %s", (guild_id,))
        row = await cursor.fetchone()
    return Settings(row[0], bool(row[1])) if row else Settings(0, False)


@asynccontextmanager
async def _mutation(guild_id, actor, expected_revision, *, admin=True):
    """Serialize feature writes per guild and reject stale previews under the lock."""
    if admin and not actor.admin:
        raise RoleError(DENIED)
    db = await get_db_connection()
    try:
        await db.begin()
        async with db.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO rp_role_settings (guild_id) VALUES (%s) ON DUPLICATE KEY UPDATE guild_id = guild_id",
                (guild_id,),
            )
            await cursor.execute(
                "SELECT revision, imported FROM rp_role_settings WHERE guild_id = %s FOR UPDATE", (guild_id,),
            )
            revision, imported = await cursor.fetchone()
            if not actor.admin and not (actor.role_ids & await _role_ids(cursor, guild_id)):
                raise RoleError(DENIED)
            if revision != expected_revision:
                raise RoleError(STALE)
            actions = []
            yield cursor, bool(imported), actions
            if actions:
                await write_admin_actions(cursor, guild_id, actor.id, actions)
                await cursor.execute(
                    "UPDATE rp_role_settings SET revision = revision + 1 WHERE guild_id = %s", (guild_id,),
                )
        await db.commit()
    except BaseException:
        if not db.closed:
            await db.rollback()
        raise
    finally:
        db.close()


async def list_characters(guild_id, user_id):
    async with _cursor() as cursor:
        await cursor.execute(
            "SELECT id, name, prefix, image_url FROM rp_characters "
            "WHERE guild_id = %s AND user_id = %s ORDER BY created_at, id",
            (guild_id, user_id),
        )
        return [Character(*row) for row in await cursor.fetchall()]


async def categories(guild_id):
    async with _cursor() as cursor:
        await cursor.execute(
            "SELECT id, name, position, mode FROM rp_role_categories WHERE guild_id = %s ORDER BY position, id",
            (guild_id,),
        )
        return [Category(*row) for row in await cursor.fetchall()]


async def _category(cursor, guild_id, category_id):
    await cursor.execute(
        "SELECT id, name, position, mode FROM rp_role_categories WHERE guild_id = %s AND id = %s",
        (guild_id, category_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise RoleError("Cette catégorie n'existe plus. Actualise le menu.")
    return Category(*row)


async def _linked_roles(cursor, guild_id, category_id):
    await cursor.execute(
        "SELECT role_id FROM rp_category_roles WHERE guild_id = %s AND category_id = %s",
        (guild_id, category_id),
    )
    return frozenset(row[0] for row in await cursor.fetchall())


async def category_roles(guild_id, category_id):
    async with _cursor() as cursor:
        category = await _category(cursor, guild_id, category_id)
        return category, await _linked_roles(cursor, guild_id, category_id)


async def profile_roles(guild_id, character_id):
    async with _cursor() as cursor:
        await cursor.execute(
            "SELECT c.id, c.name, c.position, c.mode, a.role_id FROM rp_role_categories c "
            "LEFT JOIN rp_character_roles a ON a.guild_id = c.guild_id AND a.category_id = c.id "
            "AND a.character_id = %s WHERE c.guild_id = %s ORDER BY c.position, c.id, a.role_id",
            (character_id, guild_id),
        )
        result = {}
        for category_id, name, position, mode, role_id in await cursor.fetchall():
            assigned = result.setdefault(Category(category_id, name, position, mode), [])
            if role_id is not None:
                assigned.append(role_id)
        return result


def _validate_category(name, position, mode):
    name = " ".join(name.split())
    if not name or len(name) > 80:
        raise RoleError("Utilise un nom de catégorie de 1 à 80 caractères.")
    if not 0 <= position <= 9_999_999:
        raise RoleError("L'ordre doit être compris entre 0 et 9 999 999.")
    if mode not in MODES:
        raise RoleError("Mode de sélection invalide.")
    return name


async def _insert_category(cursor, guild_id, name, position, mode):
    await cursor.execute(
        "INSERT INTO rp_role_categories (guild_id, name, position, mode) VALUES (%s, %s, %s, %s)",
        (guild_id, name, position, mode),
    )
    return cursor.lastrowid


async def save_category(guild_id, actor, revision, *, name, position, mode, category_id=None):
    name = _validate_category(name, position, mode)
    try:
        async with _mutation(guild_id, actor, revision) as (cursor, _, actions):
            if category_id is None:
                category_id = await _insert_category(cursor, guild_id, name, position, mode)
                actions.append(("rproles.category.create", f"c={category_id} ordre={position} mode={mode}"))
                actions.append(("rproles.category.name", f"{category_id} {name}"))
                return category_id

            before = await _category(cursor, guild_id, category_id)
            if before.mode == "multiple" and mode == "single":
                await cursor.execute(
                    "SELECT character_id FROM rp_character_roles WHERE guild_id = %s AND category_id = %s "
                    "GROUP BY character_id HAVING COUNT(*) > 1 LIMIT 1",
                    (guild_id, category_id),
                )
                if await cursor.fetchone():
                    raise RoleError(MODE_CONFLICT)
            await cursor.execute(
                "UPDATE rp_role_categories SET name = %s, position = %s, mode = %s WHERE guild_id = %s AND id = %s",
                (name, position, mode, guild_id, category_id),
            )
            if name != before.name:
                actions.append(("rproles.category.name", f"{category_id} {name}"))
            if (position, mode) != (before.position, before.mode):
                actions.append(("rproles.category.edit", f"c={category_id} ordre={position} mode={mode}"))
            return category_id
    except IntegrityError as exc:
        if exc.args[0] == 1761:
            raise RoleError(MODE_CONFLICT) from exc
        if exc.args[0] != 1062:
            raise
        raise RoleError("Une catégorie porte déjà ce nom sur ce serveur.") from exc


def require_roles(role_ids: Collection[int], available: Collection[int]):
    missing = set(role_ids).difference(available)
    if missing:
        ids = ", ".join(str(role_id) for role_id in sorted(missing)[:25])
        suffix = "…" if len(missing) > 25 else ""
        raise RoleError(f"Rôles Discord introuvables sur ce serveur ({len(missing)}) : {ids}{suffix}.")


async def _insert_links(cursor, guild_id, category_id, role_ids):
    await cursor.executemany(
        "INSERT INTO rp_category_roles (guild_id, category_id, role_id) VALUES (%s, %s, %s)",
        [(guild_id, category_id, role_id) for role_id in sorted(role_ids)],
    )


async def link_roles(guild_id, actor, revision, category_id, role_ids, available):
    role_ids = set(role_ids)
    require_roles(role_ids, available)
    try:
        async with _mutation(guild_id, actor, revision) as (cursor, _, actions):
            await _category(cursor, guild_id, category_id)
            await _insert_links(cursor, guild_id, category_id, role_ids)
            actions.extend(("rproles.link", f"c={category_id} r={role_id}") for role_id in sorted(role_ids))
    except IntegrityError as exc:
        if exc.args[0] != 1062:
            raise
        raise RoleError("Au moins un rôle est déjà lié à une catégorie de ce serveur.") from exc


async def _affected(cursor, guild_id, category_id, role_id, *, lock=False):
    clause = " AND role_id = %s" if role_id is not None else ""
    params = (guild_id, category_id, role_id) if role_id is not None else (guild_id, category_id)
    if not lock:
        await cursor.execute(
            "SELECT COUNT(DISTINCT character_id) FROM rp_character_roles "
            f"WHERE guild_id = %s AND category_id = %s{clause}", params,
        )
        return (await cursor.fetchone())[0]
    await cursor.execute(
        "SELECT character_id FROM rp_character_roles "
        f"WHERE guild_id = %s AND category_id = %s{clause} FOR UPDATE", params,
    )
    return len({row[0] for row in await cursor.fetchall()})


async def affected_characters(guild_id, category_id, role_id=None):
    async with _cursor() as cursor:
        return await _affected(cursor, guild_id, category_id, role_id)


async def remove_category_or_link(guild_id, actor, revision, category_id, expected_count, *, role_id=None):
    async with _mutation(guild_id, actor, revision) as (cursor, _, actions):
        await _category(cursor, guild_id, category_id)
        count = await _affected(cursor, guild_id, category_id, role_id, lock=True)
        if count != expected_count:
            raise RoleError("Le nombre de personnages concernés a changé. Recommence la confirmation.")
        if role_id is None:
            await cursor.execute(
                "DELETE FROM rp_role_categories WHERE guild_id = %s AND id = %s", (guild_id, category_id),
            )
            actions.append(("rproles.category.delete", f"c={category_id} personnages={count}"))
        else:
            await cursor.execute(
                "DELETE FROM rp_category_roles WHERE guild_id = %s AND category_id = %s AND role_id = %s",
                (guild_id, category_id, role_id),
            )
            if not cursor.rowcount:
                raise RoleError("Ce rôle n'est plus lié à cette catégorie.")
            actions.append(("rproles.unlink", f"c={category_id} r={role_id} personnages={count}"))


async def save_assignments(guild_id, actor, revision, owner_id, character_id, category_id, role_ids, available):
    role_ids = set(role_ids)
    async with _mutation(guild_id, actor, revision, admin=False) as (cursor, _, actions):
        await cursor.execute(
            "SELECT id FROM rp_characters WHERE guild_id = %s AND id = %s AND user_id = %s FOR UPDATE",
            (guild_id, character_id, owner_id),
        )
        if not await cursor.fetchone():
            raise RoleError("Ce personnage n'existe plus pour ce membre sur ce serveur.")
        category = await _category(cursor, guild_id, category_id)
        if category.mode == "single" and len(role_ids) > 1:
            raise RoleError("Cette catégorie accepte un seul rôle par personnage.")
        if not role_ids <= await _linked_roles(cursor, guild_id, category_id):
            raise RoleError("Un rôle sélectionné n'est plus lié à cette catégorie.")
        key = (guild_id, character_id, category_id)
        await cursor.execute(
            "SELECT role_id FROM rp_character_roles WHERE guild_id = %s AND character_id = %s AND category_id = %s",
            key,
        )
        current = {row[0] for row in await cursor.fetchall()}
        added, removed = role_ids - current, current - role_ids
        require_roles(added, available)

        if removed:
            await cursor.executemany(
                "DELETE FROM rp_character_roles "
                "WHERE guild_id = %s AND character_id = %s AND category_id = %s AND role_id = %s",
                [(*key, role_id) for role_id in sorted(removed)],
            )
        if added:
            await cursor.executemany(
                "INSERT INTO rp_character_roles (guild_id, character_id, category_id, role_id, mode) "
                "VALUES (%s, %s, %s, %s, %s)",
                [(*key, role_id, category.mode) for role_id in sorted(added)],
            )
        for action, roles in (("rproles.assign", added), ("rproles.remove", removed)):
            actions.extend((action, f"p={character_id} c={category_id} r={role_id}") for role_id in sorted(roles))


async def change_validator_roles(guild_id, actor, revision, role_ids, available, *, remove=False):
    role_ids = set(role_ids)
    if not remove:
        if guild_id in role_ids:
            raise RoleError("Sélectionne des rôles précis pour les validateurs. Le rôle @everyone est exclu.")
        require_roles(role_ids, available)
    async with _mutation(guild_id, actor, revision) as (cursor, _, actions):
        current = await _role_ids(cursor, guild_id)
        if remove:
            changed = role_ids & current
            sql = "DELETE FROM rp_role_validators WHERE guild_id = %s AND role_id = %s"
            action = "rproles.access.remove"
        else:
            changed = role_ids - current
            sql = "INSERT INTO rp_role_validators (guild_id, role_id) VALUES (%s, %s)"
            action = "rproles.access.add"
        if changed:
            await cursor.executemany(sql, [(guild_id, role_id) for role_id in sorted(changed)])
            actions.extend((action, f"r={role_id}") for role_id in sorted(changed))


async def import_initial(guild_id, actor, revision, seed, available):
    require_roles([role_id for _, _, role_ids in seed for role_id in role_ids], available)
    try:
        async with _mutation(guild_id, actor, revision) as (cursor, imported, actions):
            if imported:
                raise RoleError("Le jeu initial a déjà été importé sur ce serveur.")
            actions.append(("rproles.import", f"catégories={len(seed)}"))
            for position, (name, mode, role_ids) in enumerate(seed, start=1):
                category_id = await _insert_category(cursor, guild_id, name, position * 10, mode)
                await _insert_links(cursor, guild_id, category_id, role_ids)
                actions.append(("rproles.category.create", f"c={category_id} ordre={position * 10} mode={mode}"))
                actions.append(("rproles.category.name", f"{category_id} {name}"))
                actions.extend(("rproles.link", f"c={category_id} r={role_id}") for role_id in role_ids)
            await cursor.execute("UPDATE rp_role_settings SET imported = TRUE WHERE guild_id = %s", (guild_id,))
    except IntegrityError as exc:
        if exc.args[0] != 1062:
            raise
        raise RoleError("L'import rencontre un nom de catégorie ou un rôle déjà utilisé.") from exc
