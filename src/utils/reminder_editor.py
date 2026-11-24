"""French step-by-step reminder creation and editing with native member selection."""

from dataclasses import replace
import time

import discord

from src.utils import reminders as store
from src.utils.reminder_delivery import validate_destination
from src.utils.reminder_time import PastTimeError, parse_reminder_time
from src.utils.reminder_ui import NO_MENTIONS, STALE, ReminderModal, ReminderView, present, reminder_embed

STEPS = ("Titre et message", "Date", "Destination", "Mentions", "Vérification")


class ReminderEditor(ReminderView):
    def __init__(self, draft, *, step=0, editing=False):
        super().__init__(draft.guild_id, draft.user_id)
        self.draft, self.step, self.editing = draft, step, editing
        self.build()

    def embed(self):
        if self.step == 4 and self.draft.due_at:
            embed = reminder_embed(self.draft, title="Vérifie ton rappel avant d'enregistrer")
        else:
            embed = discord.Embed(title=f"⏰ {'Modifier' if self.editing else 'Créer'} un rappel · {STEPS[self.step]}",
                description={0: "Définis un titre court pour retrouver ton rappel et le message que tu souhaites recevoir.",
                             1: "Choisis un délai rapide ou indique une date personnalisée.",
                             2: "Où souhaites-tu recevoir ce rappel ?",
                             3: ("Sélectionne les membres à mentionner, sans saisir leurs identifiants."
                                 if self.draft.channel_id is not None else
                                 "Ce rappel est envoyé en message privé, uniquement à toi.\n"
                                 "Pour mentionner d'autres membres, choisis un salon d'envoi ci-dessous."),
                             4: "Vérifie le message, la date et la destination."}[self.step], color=discord.Color.blurple())
            if self.draft.title:
                embed.add_field(name="Titre", value=self.draft.title, inline=False)
            if self.draft.message:
                embed.add_field(name="Message", value=self.draft.message, inline=False)
            if self.draft.due_at:
                embed.add_field(name="Date", value=f"<t:{self.draft.due_at}:F> (<t:{self.draft.due_at}:R>)", inline=False)
            if self.step >= 2:
                embed.add_field(name="Destination", value=f"<#{self.draft.channel_id}>" if self.draft.channel_id else "Message privé")
            if self.step == 3 and self.draft.channel_id is not None:
                ids = self.draft.recipient_ids
                embed.add_field(name="Membres sélectionnés", value=" ".join(f"<@{value}>" for value in ids) or "Aucun", inline=False)
        embed.set_footer(text=f"Étape {self.step + 1}/5 · Fuseau : {self.draft.timezone} · Rien n'est enregistré avant validation")
        return embed

    def build(self):
        self.clear_items()
        if self.step == 0:
            self.button("Définir le titre et le message", self.message_modal, row=0)
        elif self.step == 1:
            select = discord.ui.Select(placeholder="Quand te le rappeler ?", row=0, options=[
                discord.SelectOption(label="Dans 10 minutes", value="10m"),
                discord.SelectOption(label="Dans 1 heure", value="1h"),
                discord.SelectOption(label="Demain à 18 h", value="demain 18:00"),
                discord.SelectOption(label="Date ou délai personnalisé", value="custom"),
            ])
            select.callback = self.choose_time
            self.add_item(select)
        elif self.step == 2:
            select = discord.ui.Select(placeholder="Destination du rappel", row=0, options=[
                discord.SelectOption(label="Message privé", value="dm"),
                discord.SelectOption(label="Salon actuel", value="current"),
                discord.SelectOption(label="Choisir un salon", value="channel"),
            ])
            select.callback = self.choose_destination
            self.add_item(select)
            channels = discord.ui.ChannelSelect(placeholder="Ou sélectionne un salon textuel", channel_types=[discord.ChannelType.text], row=1)
            channels.callback = self.choose_channel
            self.add_item(channels)
        elif self.step == 3:
            if self.draft.channel_id is None:
                channels = discord.ui.ChannelSelect(placeholder="Choisir le salon où envoyer le rappel",
                    channel_types=[discord.ChannelType.text], row=0)
                channels.callback = self.choose_channel
                self.add_item(channels)
                self.button("Utiliser le salon actuel", self.use_current_channel, row=1)
            else:
                users = discord.ui.UserSelect(placeholder="Membres à mentionner (10 maximum)", min_values=0, max_values=10, row=0,
                    default_values=[discord.SelectDefaultValue(id=value, type=discord.SelectDefaultValueType.user)
                                    for value in self.draft.recipient_ids])
                users.callback = self.choose_members
                self.add_item(users)
                self.button("Me mentionner : " + ("oui" if self.draft.mention_owner else "non"), self.toggle_owner, row=1)
                self.button("Retirer toutes les mentions", self.clear_mentions, row=1)
        elif self.step == 4:
            for label, step in (("Titre et message", 0), ("Date", 1), ("Destination", 2), ("Mentions", 3)):
                async def jump(interaction, target=step):
                    self.step = target
                    await self.redraw(interaction)
                self.button(label, jump, row=1)
            self.button("Enregistrer" if self.editing else "Programmer le rappel", self.save,
                        style=discord.ButtonStyle.success, row=2)
        self.button("Retour", self.back, row=4)
        if self.step < 4:
            self.button("Continuer", self.next, style=discord.ButtonStyle.primary, row=4)
        self.button("Annuler", self.cancel, row=4)

    async def redraw(self, interaction):
        self.build()
        await present(interaction, self)

    async def message_modal(self, interaction):
        await interaction.response.send_modal(MessageModal(self))

    async def choose_time(self, interaction):
        value = interaction.data["values"][0]
        if value == "custom":
            await interaction.response.send_modal(DateModal(self))
        else:
            self.draft = replace(self.draft, due_at=parse_reminder_time(value, self.draft.timezone))
            await self.redraw(interaction)

    async def choose_destination(self, interaction):
        value = interaction.data["values"][0]
        if value == "channel":
            await interaction.response.send_message("Sélectionne le salon dans le menu juste en dessous.", ephemeral=True)
            return
        if value == "current" and not isinstance(interaction.channel, discord.TextChannel):
            raise ValueError("Choisis un salon textuel de ce serveur.")
        self.draft = replace(self.draft, channel_id=interaction.channel_id if value == "current" else None,
                             recipient_ids=self.draft.recipient_ids if value == "current" else ())
        await self.redraw(interaction)

    async def choose_channel(self, interaction):
        await self.set_channel(interaction, int(interaction.data["values"][0]))

    async def use_current_channel(self, interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            raise ValueError("Choisis un salon textuel dans le menu ci-dessus.")
        await self.set_channel(interaction, interaction.channel_id)

    async def set_channel(self, interaction, channel_id):
        await interaction.response.defer()
        candidate = replace(self.draft, channel_id=channel_id)
        await validate_destination(interaction.client, candidate)
        self.draft = candidate
        await self.redraw(interaction)

    async def choose_members(self, interaction):
        self.draft = replace(self.draft, recipient_ids=tuple(int(value) for value in interaction.data.get("values", ())))
        await self.redraw(interaction)

    async def toggle_owner(self, interaction):
        self.draft = replace(self.draft, mention_owner=not self.draft.mention_owner)
        await self.redraw(interaction)

    async def clear_mentions(self, interaction):
        self.draft = replace(self.draft, recipient_ids=(), mention_owner=False)
        await self.redraw(interaction)

    async def back(self, interaction):
        if self.step == 0:
            await self.cancel(interaction)
            return
        self.step = 2 if self.step == 4 and self.draft.channel_id is None else self.step - 1
        await self.redraw(interaction)

    async def next(self, interaction):
        if self.step == 0 and (not self.draft.title.strip() or not self.draft.message.strip()):
            raise ValueError("Définis d'abord le titre et le message du rappel.")
        if self.step == 1 and self.draft.due_at <= time.time():
            raise ValueError("Choisis une date dans le futur.")
        if self.step == 2:
            await interaction.response.defer()
            await validate_destination(interaction.client, self.draft)
        self.step = 4 if self.step == 2 and self.draft.channel_id is None else self.step + 1
        await self.redraw(interaction)

    async def cancel(self, interaction):
        from src.utils.reminder_views import ReminderDashboard
        view = await ReminderDashboard.load(self.guild_id, self.owner_id, guild=interaction.guild)
        await self.move(interaction, view)

    async def save(self, interaction):
        if getattr(self, "saving", False) or self.is_finished():
            raise ValueError("L'enregistrement est déjà en cours.")
        self.saving = True
        try:
            await interaction.response.defer()
            if not self.draft.title.strip():
                raise ValueError("Définis le titre du rappel avec le bouton Titre et message.")
            reminder = store.validate_reminder(self.draft)
            if reminder.due_at <= time.time():
                raise ValueError("La date est passée. Reviens à l'étape Date pour choisir un nouvel horaire.")
            await validate_destination(interaction.client, reminder)
            if self.editing:
                await self.current(reminder.id, revision=reminder.revision)
                if not await store.edit_reminder(reminder):
                    raise ValueError(STALE)
                reminder = replace(reminder, revision=reminder.revision + 1, status="pending", last_error=None)
            else:
                reminder_id = await store.create_reminder(reminder, expected_generation=reminder.generation)
                reminder = await store.get_owned_reminder(reminder_id, self.guild_id, self.owner_id)
                if reminder is None:
                    raise ValueError(STALE)
            from src.utils.reminder_views import ReminderDetails
            await self.move(interaction, ReminderDetails(reminder, notice="✅ Rappel enregistré."))
        finally:
            self.saving = False


class MessageModal(ReminderModal):
    def __init__(self, parent):
        super().__init__(parent, title="Titre et message du rappel")
        self.title_input = discord.ui.TextInput(label="Titre du rappel", default=parent.draft.title or None,
                                                placeholder="Exemple : Réunion du staff", min_length=1, max_length=80)
        self.text = discord.ui.TextInput(label="Que dois-tu te rappeler ?", style=discord.TextStyle.paragraph,
                                         default=parent.draft.message or None, max_length=1000)
        self.add_item(self.title_input)
        self.add_item(self.text)

    async def on_submit(self, interaction):
        title = " ".join(self.title_input.value.split())
        if not title or len(title) > 80:
            raise ValueError("Le titre doit contenir entre 1 et 80 caractères.")
        text = self.text.value.strip()
        if not text:
            raise ValueError("Écris un message pour le rappel.")
        self.parent.draft = replace(self.parent.draft, title=title, message=text)
        await self.parent.redraw(interaction)


class DateModal(ReminderModal):
    def __init__(self, parent):
        super().__init__(parent, title="Date du rappel")
        self.when = discord.ui.TextInput(label="Date ou délai", placeholder="2h, demain 18:00, 25/12/2026 20:00", max_length=100)
        self.add_item(self.when)

    async def on_submit(self, interaction):
        try:
            due_at = parse_reminder_time(self.when.value, self.parent.draft.timezone)
        except PastTimeError as exc:
            await self.parent.move(interaction, TomorrowChoice(self.parent.draft, exc.tomorrow, editing=self.parent.editing))
            return
        self.parent.draft = replace(self.parent.draft, due_at=due_at)
        await self.parent.redraw(interaction)


class TomorrowChoice(ReminderView):
    def __init__(self, draft, tomorrow, *, editing=False):
        super().__init__(draft.guild_id, draft.user_id)
        self.draft, self.tomorrow, self.editing = draft, tomorrow, editing
        self.button(f"Choisir {tomorrow}", self.confirm, style=discord.ButtonStyle.primary)
        self.button("Choisir une autre date", self.back)

    def embed(self):
        return discord.Embed(title="Cette heure est déjà passée aujourd'hui", description=
            f"Veux-tu programmer le rappel **{self.tomorrow}** ?\nFuseau : {self.draft.timezone}", color=discord.Color.orange())

    async def confirm(self, interaction):
        due_at = parse_reminder_time(self.tomorrow, self.draft.timezone)
        await self.move(interaction, ReminderEditor(replace(self.draft, due_at=due_at), step=4, editing=self.editing))

    async def back(self, interaction):
        await self.move(interaction, ReminderEditor(self.draft, step=1, editing=self.editing))
