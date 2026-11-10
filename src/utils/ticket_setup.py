"""Owner-bound, French panel setup and management through native Discord components."""

from dataclasses import dataclass

import discord

from src.config import GUILD_IDS
from src.utils.permissions import is_admin
from src.utils.ticket_service import DEFAULT_PANEL_TEXT, DEFAULT_PANEL_TITLE, NO_MENTIONS, validate_text_channel
from src.utils.tickets import PanelDraft, TicketError
from src.utils.views import ExpiringView


@dataclass(frozen=True)
class SetupContext:
    service: object
    panel_view_factory: object
    error_handler: object
    owner_id: int
    guild_id: int


def setup_embed(interaction, title, description):
    embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
    user = interaction.client.user
    embed.set_footer(text=user.name, icon_url=user.display_avatar.url)
    return embed


class SetupView(ExpiringView):
    def __init__(self, context):
        super().__init__(timeout=600, owner_id=context.owner_id)
        self.context = context
        self.busy = False

    async def interaction_check(self, interaction):
        if not await super().interaction_check(interaction):
            return False
        if (
            interaction.guild_id != self.context.guild_id
            or interaction.guild_id not in GUILD_IDS
            or not is_admin(interaction.user)
        ):
            await interaction.response.send_message(
                "❌ Cet assistant est réservé à l'administration de ce serveur.", ephemeral=True
            )
            return False
        if self.is_finished() or self.busy:
            await interaction.response.send_message(
                "Cette action a expiré ou une opération est déjà en cours.", ephemeral=True
            )
            return False
        return True

    async def on_error(self, interaction, error, item):
        await self.context.error_handler(interaction, error)

    def button(self, label, callback, *, row=1, style=discord.ButtonStyle.secondary, disabled=False):
        item = discord.ui.Button(label=label, style=style, row=row, disabled=disabled)
        item.callback = callback
        self.add_item(item)
        return item

    async def render(self, interaction):
        self.build(interaction.guild)
        kwargs = dict(embed=self.embed(interaction), view=self, allowed_mentions=NO_MENTIONS)
        if interaction.response.is_done():
            await interaction.edit_original_response(**kwargs)
        else:
            await interaction.response.edit_message(**kwargs)

    async def show(self, interaction, view):
        view.message = self.message or interaction.message
        await view.render(interaction)
        self.stop()


class SetupHome(SetupView):
    def __init__(self, context, notice=None):
        super().__init__(context)
        self.notice = notice
        self.build(None)

    def embed(self, interaction):
        text = "Crée un panneau ou modifie un panneau existant. Chaque panneau possède ses propres rôles et destinations.\n\n"
        text += "L'assistant te guide étape par étape. Les modifications sont publiées à la dernière étape."
        if self.notice:
            text = self.notice + "\n\n" + text
        return setup_embed(interaction, "Configuration des tickets", text)

    def build(self, guild):
        self.clear_items()
        self.button("Créer un panneau", self.create, style=discord.ButtonStyle.success, row=0)
        self.button("Gérer les panneaux", self.manage, style=discord.ButtonStyle.primary, row=0)

    async def create(self, interaction):
        await self.show(interaction, PanelWizard(self.context))

    async def manage(self, interaction):
        await interaction.response.defer()
        panels = await self.context.service.panels(interaction)
        await self.show(interaction, PanelManager(self.context, panels))


class PanelTextModal(discord.ui.Modal):
    def __init__(self, wizard):
        super().__init__(title="Nom et message du panneau", timeout=600)
        self.wizard = wizard
        self.generation = wizard.generation
        draft = wizard.draft
        self.name_input = discord.ui.TextInput(
            label="Nom du panneau dans le gestionnaire", default=draft.name, max_length=80
        )
        self.title_input = discord.ui.TextInput(
            label="Titre affiché (vide = titre par défaut)", default=draft.title, required=False, max_length=256
        )
        self.text_input = discord.ui.TextInput(
            label="Texte affiché (vide = texte par défaut)",
            default=draft.text,
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=4000,
        )
        for item in (self.name_input, self.title_input, self.text_input):
            self.add_item(item)

    async def on_submit(self, interaction):
        if not await self.wizard.interaction_check(interaction):
            return
        if self.generation != self.wizard.generation or self.wizard.step != 0:
            raise TicketError("Ce formulaire n'est plus à jour. Rouvre le formulaire de cette étape.")
        name = self.name_input.value.strip()
        if not name:
            raise TicketError("Indique un nom pour retrouver ce panneau dans le gestionnaire.")
        self.wizard.draft.name = name
        self.wizard.draft.title = self.title_input.value.strip() or None
        self.wizard.draft.text = self.text_input.value.strip() or None
        self.wizard.generation += 1
        await self.wizard.render(interaction)

    async def on_error(self, interaction, error):
        await self.wizard.context.error_handler(interaction, error)


class PanelWizard(SetupView):
    STEPS = ("Nom et message", "Rôles de support", "Catégorie des tickets", "Salon des transcripts", "Envoi du panneau")

    def __init__(self, context, draft=None, *, step=0):
        super().__init__(context)
        self.draft = draft or PanelDraft()
        self.step = step
        self.generation = 0

    def embed(self, interaction):
        draft = self.draft
        instructions = (
            "Ouvre le formulaire pour définir le nom du panneau, son titre et son texte. Les champs vides gardent le message par défaut.",
            "Sélectionne de 1 à 10 rôles qui pourront voir et gérer les tickets ouverts depuis ce panneau.",
            "Sélectionne la catégorie Discord dans laquelle Aurum créera les salons privés.",
            "Choisis un salon privé pour recevoir les fichiers d'historique, ou continue sans salon. "
            "Les transcripts restent sauvegardés. Les journaux d'actions utilisent le salon général défini avec `/setlogs`.",
            "Choisis le salon où envoyer ce panneau. Vérifie les choix puis enregistre et envoie le panneau.",
        )
        embed = setup_embed(interaction, f"Étape {self.step + 1}/5 — {self.STEPS[self.step]}", instructions[self.step])
        embed.add_field(name="Nom du panneau", value=discord.utils.escape_markdown(draft.name), inline=False)
        if self.step in (0, 4):
            embed.add_field(name="Titre affiché", value=draft.title or DEFAULT_PANEL_TITLE, inline=False)
            embed.add_field(name="Texte affiché", value=(draft.text or DEFAULT_PANEL_TEXT)[:1000], inline=False)
        embed.add_field(
            name="Rôles de support", value=" ".join(f"<@&{role_id}>" for role_id in draft.staff_role_ids) or "À choisir"
        )
        embed.add_field(name="Catégorie", value=f"<#{draft.category_id}>" if draft.category_id else "À choisir")
        embed.add_field(
            name="Transcripts",
            value=f"<#{draft.transcript_channel_id}>" if draft.transcript_channel_id else "Sans envoi dans un salon",
        )
        embed.add_field(name="Salon du panneau", value=f"<#{draft.channel_id}>" if draft.channel_id else "À choisir")
        return embed

    def build(self, guild):
        self.clear_items()
        draft = self.draft
        if self.step == 0:
            self.button("Modifier le nom et le message", self.edit_text, style=discord.ButtonStyle.primary, row=0)
        elif self.step == 1:
            roles = [guild.get_role(role_id) for role_id in draft.staff_role_ids]
            select = discord.ui.RoleSelect(
                placeholder="Sélectionne les rôles de support…",
                min_values=1,
                max_values=10,
                default_values=[role for role in roles if role],
                row=0,
            )
            select.callback = self.select_roles
            self.add_item(select)
        else:
            field = {2: "category_id", 3: "transcript_channel_id", 4: "channel_id"}[self.step]
            selected = guild.get_channel(getattr(draft, field)) if getattr(draft, field) else None
            select = discord.ui.ChannelSelect(
                placeholder={
                    2: "Catégorie des salons de tickets…",
                    3: "Salon privé des transcripts (facultatif)…",
                    4: "Salon d'envoi du panneau…",
                }[self.step],
                channel_types=[discord.ChannelType.category if self.step == 2 else discord.ChannelType.text],
                min_values=0 if self.step == 3 else 1,
                max_values=1,
                default_values=[selected] if selected else [],
                row=0,
            )
            select.callback = self.select_channel
            self.add_item(select)
            if self.step == 3:
                self.button("Sans salon de transcripts", self.clear_transcripts, row=1)
        self.button("Retour", self.back, row=2)
        self.button(
            "Enregistrer et continuer" if self.step < 4 else "Enregistrer et envoyer",
            self.advance,
            row=2,
            style=discord.ButtonStyle.success,
        )
        self.button("Annuler", self.cancel, row=2)

    async def edit_text(self, interaction):
        await interaction.response.send_modal(PanelTextModal(self))

    async def select_roles(self, interaction):
        role_ids = tuple(dict.fromkeys(int(value) for value in interaction.data["values"]))
        roles = [interaction.guild.get_role(role_id) for role_id in role_ids]
        if not roles or len(roles) > 10 or any(role is None or role.is_default() or role.managed for role in roles):
            raise TicketError(
                "Choisis de 1 à 10 rôles de support dédiés, différents de @everyone et des rôles d'intégration."
            )
        self.draft.staff_role_ids = role_ids
        self.generation += 1
        await self.render(interaction)

    async def select_channel(self, interaction):
        values = interaction.data["values"]
        channel_id = int(values[0]) if values else None
        field = {2: "category_id", 3: "transcript_channel_id", 4: "channel_id"}[self.step]
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if self.step == 2:
            if not isinstance(channel, discord.CategoryChannel):
                raise TicketError("Choisis une catégorie de ce serveur.")
        elif channel_id:
            validate_text_channel(channel, interaction.guild, attachments=self.step == 3)
            if not channel.permissions_for(interaction.user).view_channel:
                raise TicketError("Tu dois pouvoir voir le salon sélectionné.")
            if self.step == 3 and channel.permissions_for(interaction.guild.default_role).view_channel:
                raise TicketError("Le salon des transcripts doit être privé.")
        elif self.step != 3:
            raise TicketError("Choisis un salon avant de continuer.")
        setattr(self.draft, field, channel_id)
        self.generation += 1
        await self.render(interaction)

    async def clear_transcripts(self, interaction):
        self.draft.transcript_channel_id = None
        self.generation += 1
        await self.render(interaction)

    async def back(self, interaction):
        if self.step == 0:
            await self.show(interaction, SetupHome(self.context, "Modifications non enregistrées abandonnées."))
            return
        self.step -= 1
        self.generation += 1
        await self.render(interaction)

    async def cancel(self, interaction):
        await self.show(interaction, SetupHome(self.context, "Modifications non enregistrées abandonnées."))

    async def advance(self, interaction):
        if self.step == 1 and not self.draft.staff_role_ids:
            raise TicketError("Sélectionne au moins un rôle de support avant de continuer.")
        if self.step == 2 and not self.draft.category_id:
            raise TicketError("Sélectionne une catégorie avant de continuer.")
        if self.step < 4:
            self.step += 1
            self.generation += 1
            await self.render(interaction)
            return
        if not self.draft.channel_id:
            raise TicketError("Sélectionne le salon d'envoi du panneau.")
        self.busy = True
        try:
            await interaction.response.defer()
            message = await self.context.service.panel(interaction, self.draft, self.context.panel_view_factory())
            await self.show(
                interaction,
                SetupHome(
                    self.context,
                    f"✅ Panneau enregistré et envoyé dans <#{self.draft.channel_id}>. [Voir le panneau]({message.jump_url})",
                ),
            )
        finally:
            self.busy = False


class PanelManager(SetupView):
    PAGE_SIZE = 25

    def __init__(self, context, panels):
        super().__init__(context)
        self.panels = panels
        self.page = 0
        self.selected_id = None
        self.confirm_delete = False

    @property
    def selected(self):
        return next((panel for panel in self.panels if panel["id"] == self.selected_id), None)

    def embed(self, interaction):
        text = "Sélectionne un panneau, puis choisis une action. Les autres panneaux restent disponibles."
        if not self.panels:
            text = "Aucun panneau enregistré. Reviens à l'accueil pour créer ton premier panneau."
        if self.confirm_delete:
            text = "**Supprimer ce panneau ?** Son menu sera désactivé. Les tickets existants et leurs historiques seront conservés."
        embed = setup_embed(interaction, "Éditeur et gestionnaire de panneaux", text)
        if self.selected:
            panel = self.selected
            embed.add_field(
                name="Panneau sélectionné", value=discord.utils.escape_markdown(panel["name"]), inline=False
            )
            embed.add_field(name="Salon du panneau", value=f"<#{panel['channel_id']}>")
            embed.add_field(
                name="Transcripts",
                value=f"<#{panel['transcript_channel_id']}>"
                if panel["transcript_channel_id"]
                else "Sans envoi dans un salon",
            )
        return embed

    def build(self, guild):
        self.clear_items()
        if self.confirm_delete:
            self.button("Confirmer la suppression", self.delete, style=discord.ButtonStyle.danger, row=0)
            self.button("Annuler", self.abort_delete, row=0)
            return
        if self.panels:
            visible = self.panels[self.page * self.PAGE_SIZE : (self.page + 1) * self.PAGE_SIZE]
            select = discord.ui.Select(
                placeholder="Sélectionne un panneau…",
                row=0,
                options=[
                    discord.SelectOption(
                        label=f"[{panel['id']}] {panel['name']}"[:100],
                        value=str(panel["id"]),
                        default=panel["id"] == self.selected_id,
                    )
                    for panel in visible
                ],
            )
            select.callback = self.choose
            self.add_item(select)
            self.button("Modifier", self.edit, row=1, style=discord.ButtonStyle.primary, disabled=self.selected is None)
            self.button("Envoyer / déplacer", self.send, row=1, disabled=self.selected is None)
            self.button(
                "Supprimer", self.ask_delete, row=1, style=discord.ButtonStyle.danger, disabled=self.selected is None
            )
            self.button("Précédent", self.previous, row=2, disabled=self.page == 0)
            self.button("Suivant", self.next, row=2, disabled=(self.page + 1) * self.PAGE_SIZE >= len(self.panels))
        self.button("Retour", self.back, row=3)
        self.button("Actualiser", self.refresh, row=3)

    async def choose(self, interaction):
        panel_id = int(interaction.data["values"][0])
        if not any(panel["id"] == panel_id for panel in self.panels):
            raise TicketError("Panneau introuvable. Actualise le gestionnaire.")
        self.selected_id = panel_id
        await self.render(interaction)

    async def edit(self, interaction):
        if not self.selected:
            raise TicketError("Sélectionne un panneau à modifier.")
        await self.show(interaction, PanelWizard(self.context, PanelDraft.from_panel(self.selected)))

    async def send(self, interaction):
        if not self.selected:
            raise TicketError("Sélectionne un panneau à envoyer.")
        await self.show(interaction, PanelWizard(self.context, PanelDraft.from_panel(self.selected), step=4))

    async def ask_delete(self, interaction):
        if not self.selected:
            raise TicketError("Sélectionne un panneau à supprimer.")
        self.confirm_delete = True
        await self.render(interaction)

    async def abort_delete(self, interaction):
        self.confirm_delete = False
        await self.render(interaction)

    async def delete(self, interaction):
        if not self.confirm_delete or not self.selected:
            raise TicketError("Confirme d'abord le panneau à supprimer.")
        self.busy = True
        try:
            await interaction.response.defer()
            await self.context.service.delete_panel(
                interaction, self.selected_id, self.selected["version"], self.context.panel_view_factory()
            )
            self.panels = await self.context.service.panels(interaction)
            self.selected_id = None
            self.confirm_delete = False
            self.page = 0
            await self.render(interaction)
        finally:
            self.busy = False

    async def previous(self, interaction):
        self.page = max(0, self.page - 1)
        self.selected_id = None
        await self.render(interaction)

    async def next(self, interaction):
        self.page = min((len(self.panels) - 1) // self.PAGE_SIZE, self.page + 1)
        self.selected_id = None
        await self.render(interaction)

    async def back(self, interaction):
        await self.show(interaction, SetupHome(self.context))

    async def refresh(self, interaction):
        await interaction.response.defer()
        self.panels = await self.context.service.panels(interaction)
        self.selected_id = None
        self.page = 0
        await self.render(interaction)
