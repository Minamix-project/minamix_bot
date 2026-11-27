"""Character selection, profile display and draft role assignments."""

from dataclasses import dataclass, replace

import discord

from src.utils import rp_roles as store
from src.utils.rp_role_ui import (
    RoleView, cached_roles, clip_text, fetch_roles, page_window, role_label, safe_text, sorted_roles,
)


def _role_fields(name, ids, roles):
    if not ids:
        return [(name, "Non renseigné", ())]
    fields = []
    lines = []
    size = 0
    shown = []
    for role_id in sorted_roles(ids, roles):
        line = f"• {safe_text(clip_text(role_label(role_id, roles), 100))}"
        if size + len(line) > 450:
            fields.append((name, "\n".join(lines), tuple(shown)))
            name = f"{name} (suite)"
            lines, shown, size = [], [], 0
        lines.append(line)
        shown.append(role_id)
        size += len(line) + 1
    fields.append((name, "\n".join(lines), tuple(shown)))
    return fields


def profile_fields(grouped, roles):
    return [
        field
        for category, ids in grouped.items()
        for field in _role_fields(category.name, ids, roles)
    ]


def _display_fields(embed, fields, roles):
    for name, description, _ in fields:
        embed.add_field(name=name, value=description, inline=False)
    for _, _, role_ids in fields:
        for role_id in role_ids:
            role = roles.get(role_id)
            if role and role.colour.value:
                embed.colour = role.colour
                return


@dataclass(frozen=True)
class Draft:
    member_id: int
    character: store.Character
    category: store.Category
    revision: int
    original: frozenset[int]
    selected: frozenset[int]
    linked: frozenset[int]


class CharacterMenu:
    def __init__(self, session, *, dashboard=None):
        self.session = session
        self.guild_id = session.guild_id
        self.dashboard = dashboard

    async def members(self, interaction):
        view = RoleView(
            self.session, interaction, "Choisir un membre", "Sélectionne le propriétaire du personnage RP.",
        )

        async def select_member(inter, values):
            member = values[0]
            if not isinstance(member, discord.Member) or member.guild.id != self.guild_id:
                raise store.RoleError("Sélectionne un membre de ce serveur.")
            await self.characters(inter, member.id)

        view.select(discord.ui.UserSelect(placeholder="Chercher un membre…", row=0), select_member)
        if self.dashboard:
            view.button("Menu principal", self.dashboard)
        view.button("Fermer", self.session.close)
        await self.session.show(interaction, view)

    async def characters(self, interaction, member_id, page=1):
        characters = await store.list_characters(self.guild_id, member_id)
        rows, page, total = page_window(characters, page)
        member = interaction.guild.get_member(member_id)
        name = safe_text(member.display_name) if member else f"Membre {member_id}"
        view = RoleView(
            self.session, interaction, "Choisir un personnage",
            f"Personnages de **{name}**." if rows else f"Aucun personnage pour **{name}**.",
        )

        async def choose(inter, values):
            await self.profile(inter, member_id, int(values[0]))

        options = [
            discord.SelectOption(label=clip_text(char.name, 100), value=str(char.id),
                                 description=f"Préfixe : {char.prefix}")
            for char in rows
        ]
        view.choices(options, "Sélectionner un personnage…", choose)
        view.pages(page, total, lambda inter, target: self.characters(inter, member_id, target))
        view.button("Autre membre", self.members)
        view.button("Actualiser", lambda inter: self.characters(inter, member_id, page))
        await self.session.show(interaction, view)

    async def profile(self, interaction, member_id, character_id, page=1, category_page=1, *, saved=False):
        characters = await store.list_characters(self.guild_id, member_id)
        index = next((i for i, char in enumerate(characters) if char.id == character_id), None)
        if index is None:
            raise store.RoleError("Ce personnage n'existe plus. Reviens à la sélection des personnages.")
        character = characters[index]
        revision = (await store.settings(self.guild_id)).revision if self.session.management else None
        grouped = await store.profile_roles(self.guild_id, character_id)
        roles = cached_roles(interaction.guild)
        fields, page, total = page_window(profile_fields(grouped, roles), page, size=4)
        description = f"Préfixe RP : **{safe_text(character.prefix)}**"
        if saved:
            description += "\nAttributions enregistrées."
        view = RoleView(self.session, interaction, character.name, description)
        if character.image_url:
            view.embed.set_thumbnail(url=character.image_url)
        _display_fields(view.embed, fields, roles)
        if not grouped:
            view.embed.add_field(name="Attributs RP", value="Aucune catégorie configurée.", inline=False)

        if self.session.management and grouped:
            category_rows, category_page, category_total = page_window(list(grouped), category_page)
            by_id = {category.id: category for category in category_rows}

            async def choose_category(inter, values):
                category = by_id[int(values[0])]
                # Read again before creating a draft. A configuration change requires refreshing the profile.
                if (await store.settings(self.guild_id)).revision != revision:
                    raise store.RoleError(store.STALE)
                _, linked = await store.category_roles(self.guild_id, category.id)
                selected = frozenset(grouped[category])
                draft = Draft(member_id, character, category, revision, selected, selected, linked)
                await self.assign(inter, draft)

            options = [discord.SelectOption(label=clip_text(c.name, 100), value=str(c.id)) for c in category_rows]
            view.choices(options, "Modifier les rôles d'une catégorie…", choose_category, row=0)
            view.pages(
                category_page, category_total,
                lambda inter, target: self.profile(inter, member_id, character_id, page, target), row=1,
            )

        view.pages(
            page, total, lambda inter, target: self.profile(inter, member_id, character_id, target, category_page),
        )
        if index > 0:
            previous = characters[index - 1].id
            view.button("Personnage précédent", lambda inter: self.profile(inter, member_id, previous), row=2)
        if index + 1 < len(characters):
            following = characters[index + 1].id
            view.button("Personnage suivant", lambda inter: self.profile(inter, member_id, following), row=2)
        list_page = index // 25 + 1
        view.button("Personnages", lambda inter: self.characters(inter, member_id, list_page))
        view.button("Actualiser", lambda inter: self.profile(inter, member_id, character_id, page, category_page))
        await self.session.show(interaction, view)

    async def assign(self, interaction, draft, page=1):
        roles = cached_roles(interaction.guild)
        editable = draft.linked & (roles.keys() | draft.original)
        available, page, total = page_window(sorted_roles(editable, roles), page)
        title = clip_text(f"{draft.character.name} · {draft.category.name}", 256)
        description = (
            f"Sélection {store.MODES[draft.category.mode].lower()} · {len(draft.selected)} rôle(s) dans le brouillon. "
            "Sélectionne un rôle pour l'ajouter ou le retirer."
        )
        if not available:
            description = "Aucun rôle disponible dans cette catégorie."
        view = RoleView(self.session, interaction, title, description)
        unavailable = len(draft.linked - roles.keys())
        if unavailable:
            view.embed.add_field(
                name="Rôles indisponibles", value=f"{unavailable} rôle(s) lié(s) sont introuvables sur Discord.",
                inline=False,
            )
        options = [
            discord.SelectOption(
                label=clip_text(role_label(role_id, roles), 100), value=str(role_id),
                description="Attribué · sélectionner pour retirer" if role_id in draft.selected else "Ajouter",
            )
            for role_id in available
        ]

        async def toggle(inter, values):
            role_id = int(values[0])
            if role_id not in available:
                raise store.RoleError("Ce rôle n'est pas disponible dans ce menu.")
            if role_id in draft.selected:
                selected = draft.selected - {role_id}
            elif draft.category.mode == "single":
                selected = frozenset({role_id})
            else:
                selected = draft.selected | {role_id}
            await self.assign(inter, replace(draft, selected=selected), page)

        async def clear(inter):
            await self.assign(inter, replace(draft, selected=frozenset()), page)

        async def back(inter):
            await self.profile(inter, draft.member_id, draft.character.id)

        view.choices(options, "Ajouter ou retirer un rôle…", toggle)
        view.pages(page, total, lambda inter, target: self.assign(inter, draft, target))
        if draft.selected:
            view.button("Vider la catégorie", clear)
        if draft.selected != draft.original:
            view.button("Prévisualiser", lambda inter: self.preview(inter, draft), style=discord.ButtonStyle.primary)
        view.button("Annuler", back)
        await self.session.show(interaction, view)

    async def preview(self, interaction, draft, page=1):
        roles = cached_roles(interaction.guild)
        added = draft.selected - draft.original
        removed = draft.original - draft.selected
        fields = []
        if added:
            fields.extend(_role_fields("Ajouts", added, roles))
        if removed:
            fields.extend(_role_fields("Retraits", removed, roles))
        fields, page, total = page_window(fields, page, size=4)
        view = RoleView(
            self.session, interaction, "Enregistrer les attributions ?",
            f"**{safe_text(draft.character.name)}** · {safe_text(draft.category.name)}\n"
            f"{len(added)} ajout(s) et {len(removed)} retrait(s).",
            timeout=120,
        )
        _display_fields(view.embed, fields, roles)

        async def confirm(inter):
            available = await fetch_roles(inter.guild) if added else {}
            actor = await self.session.authorize(inter, write=True)
            await store.save_assignments(
                self.guild_id, actor, draft.revision, draft.member_id, draft.character.id,
                draft.category.id, draft.selected, available,
            )
            await self.profile(inter, draft.member_id, draft.character.id, saved=True)

        view.pages(page, total, lambda inter, target: self.preview(inter, draft, target))
        view.confirmation(confirm, lambda inter: self.assign(inter, draft), label="Enregistrer")
        view.button("Actualiser le profil", lambda inter: self.profile(inter, draft.member_id, draft.character.id))
        await self.session.show(interaction, view)
