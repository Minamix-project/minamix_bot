"""Private category editing with immutable keys and optimistic concurrency checks."""

import discord

from src.utils.ticket_setup import SetupHome, SetupView, setup_embed
from src.utils.tickets import MAX_CATEGORIES, CategoryDraft, TicketError


class CategoryTextModal(discord.ui.Modal):
    def __init__(self, editor, draft=None):
        super().__init__(title="Créer une catégorie" if draft is not None else "Personnaliser la catégorie", timeout=600)
        self.editor = editor
        self.generation = editor.generation
        self.creating = draft is not None
        self.draft = draft if draft is not None else editor.draft
        draft = self.draft
        self.name_input = discord.ui.TextInput(label="Nom", default=draft.name, max_length=100)
        self.emoji_input = discord.ui.TextInput(label="Emoji", default=draft.emoji, max_length=100)
        self.description_input = discord.ui.TextInput(
            label="Description dans les panneaux", default=draft.description, max_length=100,
        )
        self.welcome_input = discord.ui.TextInput(
            label="Message au début du ticket", default=draft.welcome, max_length=2000, style=discord.TextStyle.paragraph,
        )
        for item in (self.name_input, self.emoji_input, self.description_input, self.welcome_input):
            self.add_item(item)

    async def on_submit(self, interaction):
        if not await self.editor.interaction_check(interaction):
            return
        if self.generation != self.editor.generation or (not self.creating and self.editor.draft is None):
            raise TicketError("Ce formulaire n'est plus à jour. Rouvre le formulaire de la catégorie.")
        draft = self.draft
        draft.name, draft.emoji = self.name_input.value.strip(), self.emoji_input.value.strip()
        draft.description, draft.welcome = self.description_input.value.strip(), self.welcome_input.value.strip()
        self.editor.draft = draft
        self.editor.generation += 1
        await self.editor.render(interaction)

    async def on_error(self, interaction, error):
        await self.editor.context.error_handler(interaction, error)


class CategoryEditor(SetupView):
    def __init__(self, context, categories, notice=None):
        super().__init__(context)
        self.categories = categories
        self.draft = None
        self.generation = 0
        self.notice = notice
        self.delete_target = None

    def embed(self, interaction):
        if self.delete_target:
            name = discord.utils.escape_markdown(self.delete_target["name"])
            return setup_embed(
                interaction, "Supprimer cette catégorie ?",
                f"**{name}** ne pourra plus être choisie dans les panneaux ni avec `/ticket create`.\n\n"
                "Les tickets existants, leurs accès, leurs historiques et leurs transcripts seront conservés.\n"
                "Ils conserveront leur catégorie et ses derniers réglages.\n\n"
                "Confirme la suppression ou annule pour revenir à l'édition.",
            )
        text = "Choisis une catégorie, puis personnalise son nom, son emoji, ses textes et ses rôles.\n"
        text += "Les modifications non enregistrées sont abandonnées lorsque tu changes de catégorie.\n"
        text += "Enregistrer actualise les panneaux et tous les tickets de cette catégorie, y compris leurs accès."
        text += f"\n{len(self.categories)}/{MAX_CATEGORIES} catégories actives."
        if not self.categories:
            text += "\nAucune catégorie disponible. Crée une catégorie pour réactiver les menus de support."
        if self.notice:
            text = self.notice + "\n\n" + text
        embed = setup_embed(interaction, "Catégories de tickets", text)
        if self.draft:
            draft = self.draft
            embed.add_field(name="Catégorie", value=f"{draft.emoji} {discord.utils.escape_markdown(draft.name)}", inline=False)
            embed.add_field(name="Description", value=draft.description or "À renseigner", inline=False)
            embed.add_field(name="Message d'ouverture", value=(draft.welcome or "À renseigner")[:1024], inline=False)
            embed.add_field(
                name="Rôles de support",
                value=" ".join(f"<@&{role_id}>" for role_id in draft.staff_role_ids) or "Aucun — administration uniquement",
                inline=False,
            )
            embed.add_field(name="Prise en charge", value="Activée" if draft.claim_enabled else "Désactivée")
        return embed

    def build(self, guild):
        self.clear_items()
        if self.delete_target:
            self.button("Confirmer la suppression", self.confirm_delete, row=0, style=discord.ButtonStyle.danger)
            self.button("Annuler", self.cancel_delete, row=0)
            return
        if self.categories:
            select = discord.ui.Select(
                placeholder="Choisis une catégorie…", row=0,
                options=[discord.SelectOption(
                    label=category["name"], value=category["category_key"], emoji=category["emoji"],
                    description=category["description"],
                    default=self.draft is not None and self.draft.category_key == category["category_key"],
                ) for category in self.categories],
            )
            select.callback = self.choose
            self.add_item(select)
        if self.draft:
            roles = [guild.get_role(role_id) for role_id in self.draft.staff_role_ids]
            role_select = discord.ui.RoleSelect(
                placeholder="Rôles de support (facultatif)…", min_values=0, max_values=10, row=1,
                default_values=[role for role in roles if role],
            )
            role_select.callback = self.select_roles
            self.add_item(role_select)
            self.button("Modifier le nom et les textes", self.edit, row=2, style=discord.ButtonStyle.primary)
            self.button("Créer" if self.draft.version == 0 else "Enregistrer", self.save, row=2, style=discord.ButtonStyle.success)
            self.button("Annuler les modifications", self.discard, row=2)
            self.button("Prise en charge : Oui" if self.draft.claim_enabled else "Prise en charge : Non",
                        self.toggle_claim, row=2,
                        style=discord.ButtonStyle.success if self.draft.claim_enabled else discord.ButtonStyle.secondary)
            if self.draft.version:
                self.button("Supprimer", self.ask_delete, row=2, style=discord.ButtonStyle.danger)
        self.button("Créer une catégorie", self.create, row=3, style=discord.ButtonStyle.primary,
                    disabled=len(self.categories) >= MAX_CATEGORIES)
        self.button("Retour", self.back, row=3)

    async def create(self, interaction):
        if len(self.categories) >= MAX_CATEGORIES:
            raise TicketError(f"Tu peux créer au maximum {MAX_CATEGORIES} catégories actives par serveur.")
        self.generation += 1
        draft = CategoryDraft(
            category_key="", name="Nouvelle catégorie", emoji="🎫", description="Pour contacter le staff",
            welcome="Explique ta demande et donne les détails utiles au staff.", version=0,
        )
        await interaction.response.send_modal(CategoryTextModal(self, draft))

    async def choose(self, interaction):
        key = interaction.data["values"][0]
        category = next((category for category in self.categories if category["category_key"] == key), None)
        if category is None:
            raise TicketError("Cette catégorie n'est plus disponible. Rouvre le gestionnaire.")
        self.draft = CategoryDraft.from_category(category)
        self.generation += 1
        self.notice = None
        await self.render(interaction)

    async def select_roles(self, interaction):
        from src.utils.ticket_service import validate_staff_roles
        role_ids = tuple(dict.fromkeys(int(value) for value in interaction.data["values"]))
        validate_staff_roles(interaction.guild, [interaction.guild.get_role(role_id) for role_id in role_ids])
        self.draft.staff_role_ids = role_ids
        self.generation += 1
        await self.render(interaction)

    async def edit(self, interaction):
        await interaction.response.send_modal(CategoryTextModal(self))

    async def toggle_claim(self, interaction):
        self.draft.claim_enabled = not self.draft.claim_enabled
        self.generation += 1
        await self.render(interaction)

    async def discard(self, interaction):
        self.draft = None
        self.generation += 1
        await self.render(interaction)

    async def save(self, interaction):
        if self.draft is None:
            raise TicketError("Choisis une catégorie avant d'enregistrer.")
        self.busy = True
        try:
            await interaction.response.defer()
            await self.context.service.save_category(interaction, self.draft, self.context.panel_view_factory)
            self.categories = await self.context.service.categories(interaction)
            self.draft = None
            self.notice = "✅ Catégorie enregistrée. Les panneaux et tickets associés ont été actualisés."
            self.generation += 1
            await self.render(interaction)
        finally:
            self.busy = False

    async def ask_delete(self, interaction):
        if self.draft is None or self.draft.version == 0:
            raise TicketError("Choisis une catégorie enregistrée à supprimer.")
        self.delete_target = next(
            (dict(category) for category in self.categories if category["category_key"] == self.draft.category_key), None,
        )
        if self.delete_target is None:
            raise TicketError("Cette catégorie n'est plus disponible. Rouvre le gestionnaire.")
        self.generation += 1
        await self.render(interaction)

    async def cancel_delete(self, interaction):
        self.delete_target = None
        self.generation += 1
        await self.render(interaction)

    async def confirm_delete(self, interaction):
        if self.delete_target is None:
            raise TicketError("Confirme d'abord la catégorie à supprimer.")
        self.busy = True
        try:
            await interaction.response.defer()
            target = self.delete_target
            await self.context.service.delete_category(
                interaction, target["category_key"], target["version"], self.context.panel_view_factory,
            )
            self.categories = await self.context.service.categories(interaction)
            self.delete_target = self.draft = None
            self.generation += 1
            self.notice = "✅ Catégorie supprimée. Les tickets existants et leurs accès sont conservés."
            await self.render(interaction)
        finally:
            self.busy = False

    async def back(self, interaction):
        await self.show(interaction, SetupHome(self.context))
