"""Personal reminder dashboard, history, preferences and destructive confirmations."""

import time
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from src.utils import reminders as store
from src.utils.reminder_delivery import validate_destination
from src.utils.reminder_editor import ReminderEditor
from src.utils.reminder_ui import STALE, ReminderModal, ReminderView, present, reminder_embed

TABS = {"pending": "À venir", "failed": "Échecs", "sent": "Envoyés récemment"}


class ReminderDashboard(ReminderView):
    def __init__(self, guild_id, user_id, records, preferences, *, tab="pending", page=0, guild=None):
        super().__init__(guild_id, user_id)
        self.preferences, self.tab = preferences, tab
        self.records = [record for record in records if record.status in {
            "pending": {"pending", "sending"}, "failed": {"failed"}, "sent": {"sent"}}[tab]]
        self.page = min(max(page, 0), max(0, (len(self.records) - 1) // 5))
        select = discord.ui.Select(placeholder="Afficher…", row=0, options=[
            discord.SelectOption(label=label, value=key, default=key == tab) for key, label in TABS.items()])
        select.callback = self.choose_tab
        self.add_item(select)
        shown = self.records[self.page * 5:self.page * 5 + 5]
        if shown:
            select = discord.ui.Select(placeholder="Choisis un rappel pour le gérer", row=1, options=[
                discord.SelectOption(label=f"#{record.reference} · {record.message}"[:100], value=str(record.id),
                    description=(datetime.fromtimestamp(record.due_at, ZoneInfo(preferences["timezone"])).strftime("%d/%m %H:%M %Z") + " · " +
                                ("Message privé" if record.channel_id is None else
                                 f"#{guild.get_channel(record.channel_id).name}" if guild and guild.get_channel(record.channel_id) else "Salon du serveur"))[:100]) for record in shown])
            select.callback = self.choose_reminder
            self.add_item(select)
        self.button("Précédent", self.previous, row=3, disabled=self.page == 0)
        self.button("Suivant", self.next, row=3, disabled=(self.page + 1) * 5 >= len(self.records))
        self.button("Actualiser", self.refresh, row=3)
        self.button("Créer un rappel", self.create, row=4, style=discord.ButtonStyle.success)
        self.button("Mon fuseau horaire", self.settings, row=4)
        self.button("Réinitialiser mes rappels", self.reset, row=4, style=discord.ButtonStyle.danger)

    @classmethod
    async def load(cls, guild_id, user_id, *, tab="pending", page=0, guild=None):
        records = await store.list_reminders(guild_id, user_id, tab="sent" if tab == "sent" else "active")
        return cls(guild_id, user_id, records, await store.get_preferences(guild_id, user_id), tab=tab, page=page, guild=guild)

    def embed(self):
        embed = discord.Embed(title=f"⏰ Tes rappels · {TABS[self.tab]}", color=discord.Color.blurple(),
            description="Choisis un rappel dans le menu pour le modifier, le reporter ou le supprimer."
                        if self.records else "Aucun rappel dans cette rubrique. Tu peux en créer un avec le bouton ci-dessous.")
        for record in self.records[self.page * 5:self.page * 5 + 5]:
            target = f"<#{record.channel_id}>" if record.channel_id else "Message privé"
            previous = " · ancienne série" if record.generation != self.preferences["generation"] else ""
            embed.add_field(name=f"#{record.reference} · {store.CATEGORIES[record.category]}{previous}",
                value=f"{record.message[:220]}\n<t:{record.due_at}:F> (<t:{record.due_at}:R>) · {target}" +
                      ("\n📨 En cours d'envoi" if record.status == "sending" else ""), inline=False)
        embed.set_footer(text=f"Page {self.page + 1}/{max(1, (len(self.records) + 4) // 5)} · "
                         f"Fuseau : {self.preferences['timezone']} · Historique conservé 30 jours")
        return embed

    async def reload(self, interaction, *, tab=None, page=None):
        await interaction.response.defer()
        view = await self.load(self.guild_id, self.owner_id, tab=tab or self.tab, page=self.page if page is None else page, guild=interaction.guild)
        await self.move(interaction, view)

    async def choose_tab(self, interaction):
        await self.reload(interaction, tab=interaction.data["values"][0], page=0)

    async def choose_reminder(self, interaction):
        await interaction.response.defer()
        reminder_id = int(interaction.data["values"][0])
        if reminder_id not in {record.id for record in self.records[self.page * 5:self.page * 5 + 5]}:
            raise ValueError(STALE)
        reminder = await self.current(reminder_id, mutable=False)
        await self.move(interaction, ReminderDetails(reminder))

    async def previous(self, interaction):
        await self.reload(interaction, page=max(0, self.page - 1))

    async def next(self, interaction):
        await self.reload(interaction, page=self.page + 1)

    async def refresh(self, interaction):
        await self.reload(interaction)

    async def create(self, interaction):
        await interaction.response.defer()
        prefs = await store.get_preferences(self.guild_id, self.owner_id)
        draft = store.Reminder(self.guild_id, self.owner_id, None, 0, "", timezone=prefs["timezone"], generation=prefs["generation"])
        await self.move(interaction, ReminderEditor(draft))

    async def settings(self, interaction):
        await self.move(interaction, TimezoneSettings(self.guild_id, self.owner_id, self.preferences["timezone"]))

    async def reset(self, interaction):
        await interaction.response.defer()
        records = await store.list_reminders(self.guild_id, self.owner_id)
        prefs = await store.get_preferences(self.guild_id, self.owner_id)
        expected = tuple(sorted((record.id, record.revision, record.status) for record in records))
        await self.move(interaction, ResetConfirmation(self.guild_id, self.owner_id, prefs["generation"], expected))


class ReminderDetails(ReminderView):
    def __init__(self, reminder, *, notice=None):
        super().__init__(reminder.guild_id, reminder.user_id)
        self.reminder, self.notice = reminder, notice
        if reminder.status in {"pending", "failed"}:
            self.button("Corriger et réessayer" if reminder.status == "failed" else "Modifier", self.edit, row=0,
                        style=discord.ButtonStyle.primary)
            self.button("Supprimer", self.delete, row=0, style=discord.ButtonStyle.danger)
        if reminder.status in {"pending", "failed", "sent"}:
            self.button("Reporter de 10 min", self.snooze_short, row=1)
            self.button("Reporter de 1 heure", self.snooze_long, row=1)
        self.button("Retour à mes rappels", self.back, row=2)

    def embed(self):
        embed = reminder_embed(self.reminder)
        if self.notice:
            embed.title = f"{self.notice} · #{self.reminder.reference}"
        if self.reminder.status == "sent":
            embed.add_field(name="Historique", value="Ce rappel a déjà été envoyé. Un report crée un nouveau rappel personnel.", inline=False)
        return embed

    async def edit(self, interaction):
        await interaction.response.defer()
        reminder = await self.current(self.reminder.id, revision=self.reminder.revision)
        await self.move(interaction, ReminderEditor(reminder, step=1 if reminder.due_at <= time.time() else 4, editing=True))

    async def delete(self, interaction):
        await interaction.response.defer()
        reminder = await self.current(self.reminder.id, revision=self.reminder.revision)
        await self.move(interaction, DeleteConfirmation(reminder))

    async def snooze(self, interaction, delay):
        await interaction.response.defer()
        reminder = await self.current(self.reminder.id, revision=self.reminder.revision, mutable=self.reminder.status != "sent")
        updated = replace(reminder, due_at=int(time.time()) + delay)
        await validate_destination(interaction.client, updated)
        if reminder.status == "sent":
            reminder_id = await store.snooze_reminder(reminder, updated.due_at)
        else:
            if not await store.edit_reminder(updated):
                raise ValueError(STALE)
            reminder_id = reminder.id
        saved = await store.get_owned_reminder(reminder_id, self.guild_id, self.owner_id)
        await self.move(interaction, ReminderDetails(saved, notice="✅ Rappel reporté."))

    async def snooze_short(self, interaction):
        await self.snooze(interaction, 600)

    async def snooze_long(self, interaction):
        await self.snooze(interaction, 3600)

    async def back(self, interaction):
        await interaction.response.defer()
        await self.move(interaction, await ReminderDashboard.load(self.guild_id, self.owner_id, guild=interaction.guild))


class DeleteConfirmation(ReminderView):
    def __init__(self, reminder):
        super().__init__(reminder.guild_id, reminder.user_id)
        self.reminder, self.used = reminder, False
        self.button("Supprimer ce rappel", self.confirm, style=discord.ButtonStyle.danger)
        self.button("Annuler", self.cancel)

    def embed(self):
        return reminder_embed(self.reminder, title=f"Supprimer ton rappel #{self.reminder.reference} ?")

    async def confirm(self, interaction):
        if self.used:
            raise ValueError("Cette confirmation a déjà été utilisée.")
        self.used = True
        await interaction.response.defer()
        await self.current(self.reminder.id, revision=self.reminder.revision)
        if not await store.delete_reminder(self.reminder.id, self.guild_id, self.owner_id, revision=self.reminder.revision):
            raise ValueError(STALE)
        await self.move(interaction, await ReminderDashboard.load(self.guild_id, self.owner_id, guild=interaction.guild))

    async def cancel(self, interaction):
        await self.move(interaction, ReminderDetails(await self.current(self.reminder.id, mutable=False)))


class ResetConfirmation(ReminderView):
    def __init__(self, guild_id, user_id, generation, expected):
        super().__init__(guild_id, user_id)
        self.generation, self.expected, self.used = generation, expected, False
        self.button("Réinitialiser mes rappels", self.confirm, style=discord.ButtonStyle.danger)
        self.button("Annuler", self.cancel)

    def embed(self):
        return discord.Embed(title="Remettre tes rappels à zéro sur ce serveur ?", color=discord.Color.red(),
            description=f"**{len(self.expected)} rappel(s)** en attente ou en échec seront supprimés. "
            "Ton prochain rappel portera le numéro **#1**.\n\n"
            "Les rappels des autres membres sont conservés, ainsi que ton historique d'envoi et ton fuseau horaire. "
            "Un rappel en cours d'envoi empêche la remise à zéro.")

    async def confirm(self, interaction):
        if self.used:
            raise ValueError("Cette confirmation a déjà été utilisée.")
        self.used = True
        await interaction.response.defer()
        await store.reset_reminders(self.guild_id, self.owner_id, self.generation, self.expected)
        await self.move(interaction, await ReminderDashboard.load(self.guild_id, self.owner_id, guild=interaction.guild))

    async def cancel(self, interaction):
        await interaction.response.defer()
        await self.move(interaction, await ReminderDashboard.load(self.guild_id, self.owner_id, guild=interaction.guild))


class TimezoneSettings(ReminderView):
    def __init__(self, guild_id, user_id, timezone):
        super().__init__(guild_id, user_id)
        self.timezone = timezone
        select = discord.ui.Select(placeholder="Ton fuseau horaire", options=[
            discord.SelectOption(label=label, value=value) for label, value in (
                ("Paris / Bruxelles", "Europe/Brussels"),
                ("Québec · Montréal", "America/Montreal"), ("Temps universel · UTC", "UTC"))])
        select.callback = self.choose
        self.add_item(select)
        self.button("Autre fuseau", self.custom, row=1)
        self.button("Retour", self.back, row=1)

    def embed(self):
        return discord.Embed(title="Ton fuseau horaire", description=f"Fuseau actuel : **{self.timezone}**.\n"
            "Ce choix est mémorisé pour toi sur ce serveur. Les rappels déjà programmés conservent leur horaire.",
            color=discord.Color.blurple())

    async def choose(self, interaction):
        await interaction.response.defer()
        value = interaction.data["values"][0]
        await store.save_timezone(self.guild_id, self.owner_id, value)
        self.timezone = value
        await present(interaction, self)

    async def custom(self, interaction):
        await interaction.response.send_modal(TimezoneModal(self))

    async def back(self, interaction):
        await interaction.response.defer()
        await self.move(interaction, await ReminderDashboard.load(self.guild_id, self.owner_id, guild=interaction.guild))


class TimezoneModal(ReminderModal):
    def __init__(self, parent):
        super().__init__(parent, title="Choisir un autre fuseau")
        self.zone = discord.ui.TextInput(label="Nom du fuseau horaire", default=parent.timezone, max_length=64,
                                         placeholder="Exemple : America/Guadeloupe")
        self.add_item(self.zone)

    async def on_submit(self, interaction):
        await interaction.response.defer()
        value = self.zone.value.strip()
        await store.save_timezone(self.parent.guild_id, self.parent.owner_id, value)
        self.parent.timezone = value
        await present(interaction, self.parent)
