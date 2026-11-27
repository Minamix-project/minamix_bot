"""Administrative screens for role categories, delegation and the optional import."""

import discord

from src.utils import rp_roles as store
from src.utils.rp_role_seed import AURUM_ROLES
from src.utils.rp_role_ui import (
    RoleModal, RoleView, cached_roles, clip_text, fetch_roles, page_window, role_label, safe_text, sorted_roles,
)


def _role_options(role_ids, roles):
    return [
        discord.SelectOption(label=clip_text(role_label(role_id, roles), 100), value=str(role_id))
        for role_id in role_ids
    ]


class CategoryModal(RoleModal):
    def __init__(self, parent, menu, revision, category=None):
        super().__init__(parent, title="Modifier la catégorie" if category else "Créer une catégorie")
        self.menu = menu
        self.revision = revision
        self.category = category
        self.category_name = discord.ui.TextInput(
            label="Nom", max_length=80, default=category.name if category else None,
        )
        self.position = discord.ui.TextInput(
            label="Ordre (0 à 9 999 999)", max_length=7, default=str(category.position) if category else "10",
        )
        self.add_item(self.category_name)
        self.add_item(self.position)

    async def submit(self, interaction):
        try:
            position = int(self.position.value)
        except ValueError as exc:
            raise store.RoleError("Saisis un nombre entier pour l'ordre de la catégorie.") from exc
        actor = await self.menu.session.authorize(interaction, admin=True, write=True)
        category_id = await store.save_category(
            self.menu.guild_id, actor, self.revision, name=self.category_name.value, position=position,
            mode=self.category.mode if self.category else "single",
            category_id=self.category.id if self.category else None,
        )
        await self.menu.category(interaction, category_id)


class AdminRoleMenu:
    def __init__(self, session, dashboard):
        self.session = session
        self.guild_id = session.guild_id
        self.dashboard = dashboard

    async def categories(self, interaction, page=1):
        await self.session.authorize(interaction, admin=True)
        settings = await store.settings(self.guild_id)
        categories = await store.categories(self.guild_id)
        rows, page, total = page_window(categories, page)
        description = "Sélectionne une catégorie pour modifier ses paramètres ou ses rôles liés."
        if not rows:
            description = "Aucune catégorie RP configurée sur ce serveur."
        view = RoleView(self.session, interaction, "Catégories RP", description, admin=True)
        options = [
            discord.SelectOption(label=clip_text(c.name, 100), value=str(c.id),
                                 description=f"{store.MODES[c.mode]} · Ordre {c.position}")
            for c in rows
        ]

        async def create(inter):
            await inter.response.send_modal(CategoryModal(view, self, settings.revision))

        async def select(inter, values):
            await self.category(inter, int(values[0]))

        view.choices(options, "Sélectionner une catégorie…", select)
        view.pages(page, total, self.categories)
        view.button("Créer une catégorie", create, defer=False, style=discord.ButtonStyle.primary, row=2)
        if not settings.imported:
            view.button("Importer les rôles RP initiaux", self.import_preview, row=2)
        view.button("Menu principal", self.dashboard)
        view.button("Actualiser", lambda inter: self.categories(inter, page))
        await self.session.show(interaction, view)

    async def category(self, interaction, category_id, page=1):
        settings = await store.settings(self.guild_id)
        category, ids = await store.category_roles(self.guild_id, category_id)
        roles = cached_roles(interaction.guild)
        rows, page, total = page_window(sorted_roles(ids, roles), page)
        description = (
            f"Sélection **{store.MODES[category.mode].lower()}** · Ordre **{category.position}**\n"
            f"{len(ids)} rôle(s) lié(s), dont {len(ids - roles.keys())} indisponible(s)."
        )
        view = RoleView(self.session, interaction, category.name, description, admin=True)

        async def link(inter, values):
            available = await fetch_roles(inter.guild)
            actor = await self.session.authorize(inter, admin=True, write=True)
            await store.link_roles(
                self.guild_id, actor, settings.revision, category_id, [role.id for role in values], available,
            )
            await self.category(inter, category_id, page)

        async def unlink(inter, values):
            role_id = int(values[0])
            if role_id not in rows:
                raise store.RoleError("Ce rôle n'est plus dans cette liste.")
            await self.remove_preview(inter, category, settings.revision, role_id=role_id, page=page)

        async def edit(inter):
            await inter.response.send_modal(CategoryModal(view, self, settings.revision, category))

        async def mode(inter, values):
            actor = await self.session.authorize(inter, admin=True, write=True)
            await store.save_category(
                self.guild_id, actor, settings.revision, category_id=category_id,
                name=category.name, position=category.position, mode=values[0],
            )
            await self.category(inter, category_id, page)

        view.select(discord.ui.RoleSelect(placeholder="Lier des rôles Discord…", max_values=25, row=0), link)
        view.choices(_role_options(rows, roles), "Choisir un rôle à délier…", unlink, row=1)
        modes = [
            discord.SelectOption(label=label, value=value, default=value == category.mode)
            for value, label in store.MODES.items()
        ]
        view.choices(modes, "Mode de sélection…", mode, row=2)
        view.pages(page, total, lambda inter, target: self.category(inter, category_id, target))
        view.button("Modifier le nom ou l'ordre", edit, defer=False)
        view.button(
            "Supprimer la catégorie", lambda inter: self.remove_preview(inter, category, settings.revision, page=page),
            style=discord.ButtonStyle.danger,
        )
        view.button("Catégories", self.categories)
        view.button("Actualiser", lambda inter: self.category(inter, category_id, page))
        await self.session.show(interaction, view)

    async def remove_preview(self, interaction, category, revision, *, role_id=None, page=1):
        if (await store.settings(self.guild_id)).revision != revision:
            raise store.RoleError(store.STALE)
        count = await store.affected_characters(self.guild_id, category.id, role_id)
        title = "Supprimer la catégorie ?" if role_id is None else "Délier ce rôle ?"
        description = f"Catégorie **{safe_text(category.name)}**"
        if role_id is not None:
            description += f" · **{safe_text(role_label(role_id, cached_roles(interaction.guild)))}**"
        description += f"\nAttributions retirées pour **{count} personnage(s)**."
        view = RoleView(self.session, interaction, title, description, admin=True, timeout=60)

        async def confirm(inter):
            actor = await self.session.authorize(inter, admin=True, write=True)
            await store.remove_category_or_link(self.guild_id, actor, revision, category.id, count, role_id=role_id)
            if role_id is None:
                await self.categories(inter)
            else:
                await self.category(inter, category.id, page)

        view.confirmation(
            confirm, lambda inter: self.category(inter, category.id, page),
            label="Supprimer" if role_id is None else "Délier",
        )
        await self.session.show(interaction, view)

    async def access(self, interaction, page=1):
        await self.session.authorize(interaction, admin=True)
        settings = await store.settings(self.guild_id)
        ids = await store.validator_roles(self.guild_id)
        roles = cached_roles(interaction.guild)
        rows, page, total = page_window(sorted_roles(ids, roles), page)
        description = (
            f"Rôles habilités : **{len(ids)}**, dont **{len(ids - roles.keys())}** indisponible(s)."
            if ids else "Aucun rôle de validation configuré."
        )
        view = RoleView(self.session, interaction, "Accès aux attributions RP", description, admin=True)

        async def add(inter, values):
            available = await fetch_roles(inter.guild)
            actor = await self.session.authorize(inter, admin=True, write=True)
            await store.change_validator_roles(
                self.guild_id, actor, settings.revision, [role.id for role in values], available,
            )
            await self.access(inter, page)

        async def remove(inter, values):
            role_id = int(values[0])
            if role_id not in rows:
                raise store.RoleError("Ce rôle n'est plus dans cette liste.")
            actor = await self.session.authorize(inter, admin=True, write=True)
            await store.change_validator_roles(
                self.guild_id, actor, settings.revision, [role_id], {}, remove=True,
            )
            await self.access(inter, page)

        view.select(discord.ui.RoleSelect(placeholder="Habiliter des rôles de validation…", max_values=25, row=0), add)
        view.choices(_role_options(rows, roles), "Retirer l'accès à un rôle…", remove, row=1)
        view.pages(page, total, self.access)
        view.button("Menu principal", self.dashboard)
        view.button("Actualiser", lambda inter: self.access(inter, page))
        await self.session.show(interaction, view)

    async def import_preview(self, interaction):
        settings = await store.settings(self.guild_id)
        if settings.imported:
            raise store.RoleError("Le jeu initial a déjà été importé sur ce serveur.")
        available = await fetch_roles(interaction.guild)
        ids = [role_id for _, _, role_ids in AURUM_ROLES for role_id in role_ids]
        store.require_roles(ids, available)
        view = RoleView(
            self.session, interaction, "Importer les rôles RP initiaux ?",
            f"**{len(AURUM_ROLES)} catégories et {len(ids)} rôles Discord** seront liés sur ce serveur.",
            admin=True, timeout=120,
        )
        for name, mode, role_ids in AURUM_ROLES:
            label = f"{name} · {store.MODES[mode]}"
            lines = [f"• {safe_text(clip_text(available[role_id].name, 50))}" for role_id in role_ids]
            view.embed.add_field(name=label, value="\n".join(lines), inline=False)

        async def confirm(inter):
            current = await fetch_roles(inter.guild)
            actor = await self.session.authorize(inter, admin=True, write=True)
            await store.import_initial(self.guild_id, actor, settings.revision, AURUM_ROLES, current)
            await self.categories(inter)

        view.confirmation(confirm, self.categories, label="Importer")
        await self.session.show(interaction, view)
