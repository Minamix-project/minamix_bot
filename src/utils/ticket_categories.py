"""Private category editing with immutable keys and optimistic concurrency checks."""

import discord

from src.utils.ticket_setup import SetupHome, SetupView, setup_embed
from src.utils.tickets import CategoryDraft, TicketError


class CategoryTextModal(discord.ui.Modal):
    def __init__(self, editor):
        super().__init__(title="Personnaliser la catégorie", timeout=600)
        self.editor = editor
        self.generation = editor.generation
        draft = editor.draft
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
        if self.generation != self.editor.generation or self.editor.draft is None:
            raise TicketError("Ce formulaire n'est plus à jour. Rouvre le formulaire de la catégorie.")
        draft = self.editor.draft
        draft.name, draft.emoji = self.name_input.value.strip(), self.emoji_input.value.strip()
        draft.description, draft.welcome = self.description_input.value.strip(), self.welcome_input.value.strip()
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

    def embed(self, interaction):
        text = "Choisis une catégorie, puis personnalise son nom, son emoji, ses textes et ses rôles.\n"
        text += "Les modifications non enregistrées sont abandonnées lorsque tu changes de catégorie.\n"
        text += "Enregistrer actualise les panneaux et tous les tickets de cette catégorie, y compris leurs accès."
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
        return embed

    def build(self, guild):
        self.clear_items()
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
            self.button("Enregistrer", self.save, row=2, style=discord.ButtonStyle.success)
            self.button("Annuler les modifications", self.discard, row=2)
        self.button("Retour", self.back, row=3)

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

    async def back(self, interaction):
        await self.show(interaction, SetupHome(self.context))
