"""Reminder shortcuts and the private French interactive reminder manager."""

from dataclasses import replace
from datetime import datetime
import time
from typing import Literal
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from src.utils.reminder_delivery import parse_recipients, validate_destination
from src.utils.reminder_editor import ReminderEditor, TomorrowChoice
from src.utils.reminder_time import DEFAULT_TIMEZONE, PastTimeError, parse_reminder_time
from src.utils.reminder_ui import NO_MENTIONS, STALE, reminder_embed, send_view, ui_error
from src.utils.reminder_views import DeleteConfirmation, ReminderDashboard, ReminderDetails, ResetConfirmation
from src.utils.reminders import (
    CATEGORIES, Reminder, create_reminder, edit_reminder, get_owned_reminder,
    get_preferences, list_reminders, resolve_reminder, validate_reminder,
)

Delivery = Literal["dm", "current", "channel"]
Category = Literal["custom", "staff_meeting", "deadline", "ooc_event", "rp_event"]
_DELIVERY_CHOICES = [app_commands.Choice(name=label, value=value) for label, value in
                     (("Message privé", "dm"), ("Salon actuel", "current"), ("Salon choisi", "channel"))]
_CATEGORY_CHOICES = [app_commands.Choice(name=label, value=value) for value, label in CATEGORIES.items()]


def destination(interaction, delivery, channel, previous=None):
    if channel is not None:
        if delivery not in {None, "channel"}:
            raise ValueError("Choisis l'envoi dans un salon pour sélectionner un salon de destination.")
        return channel.id
    if delivery == "channel":
        raise ValueError("Sélectionne une destination avec l'option channel.")
    if delivery == "dm":
        return None
    if delivery == "current":
        if not isinstance(interaction.channel, discord.TextChannel):
            raise ValueError("Sélectionne un salon textuel du serveur avec l'option channel.")
        return interaction.channel_id
    return previous


def summary(reminder):
    target = f"dans <#{reminder.channel_id}>" if reminder.channel_id else "en message privé"
    return f"Rappel **#{reminder.reference}** programmé pour le <t:{reminder.due_at}:F> (<t:{reminder.due_at}:R>), {target}."


@app_commands.guild_only()
class Remind(app_commands.Group):
    def __init__(self):
        super().__init__(name="reminder", description="Créer et gérer tes rappels.")

    async def on_error(self, interaction, error):
        from src.utils.command_errors import ERROR_HANDLED_KEY
        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
        if isinstance(original, app_commands.CommandOnCooldown):
            original = ValueError(f"Patiente {int(original.retry_after) + 1} secondes avant de créer un autre rappel.")
        await ui_error(interaction, original)
        interaction.extras[ERROR_HANDLED_KEY] = True

    @app_commands.command(name="create", description="Ouvrir l'assistant de rappel, ou programmer directement avec when et text.")
    @app_commands.checks.cooldown(3, 60, key=lambda interaction: (interaction.guild_id, interaction.user.id))
    @app_commands.choices(delivery=_DELIVERY_CHOICES, category=_CATEGORY_CHOICES)
    @app_commands.describe(
        when="Facultatif : 2h, demain 18:00 ou 25/12/2026 20:00 ; sinon utilise l'assistant",
        text="Le message du rappel (1 000 caractères maximum)", delivery="Message privé ou salon",
        channel="Salon textuel de destination", timezone="Fuseau du nouvel horaire ; ton choix mémorisé par défaut",
        mention="Te mentionner lors de l'envoi", recipients="Mentions séparées par espaces ou virgules ; sélection visuelle dans l'assistant",
        category="Catégorie facultative",
    )
    async def create(self, interaction: discord.Interaction, when: str | None = None, text: str | None = None,
                     delivery: Delivery | None = None, channel: discord.TextChannel | None = None,
                     timezone: str | None = None, mention: bool = True, recipients: str | None = None,
                     category: Category = "custom"):
        await interaction.response.defer(ephemeral=True)
        preferences = await get_preferences(interaction.guild_id, interaction.user.id)
        reminder = Reminder(interaction.guild_id, interaction.user.id, destination(interaction, delivery, channel), 0, text or "",
            category=category, mention_owner=mention, recipient_ids=parse_recipients(recipients) if recipients is not None else (),
            timezone=timezone or preferences["timezone"], generation=preferences["generation"])
        if when is not None:
            try:
                reminder = replace(reminder, due_at=parse_reminder_time(when, reminder.timezone))
            except PastTimeError as exc:
                await send_view(interaction, TomorrowChoice(reminder, exc.tomorrow))
                return
        if when is None or text is None:
            await send_view(interaction, ReminderEditor(reminder, step=1 if reminder.message else 0))
            return
        reminder = validate_reminder(reminder)
        await validate_destination(interaction.client, reminder)
        reminder_id = await create_reminder(reminder)
        reminder = await get_owned_reminder(reminder_id, reminder.guild_id, reminder.user_id)
        if reminder is None:
            raise ValueError(STALE)
        view = ReminderDetails(reminder)
        view.message = await interaction.followup.send(summary(reminder), embed=reminder_embed(reminder), view=view,
                                                       ephemeral=True, wait=True, allowed_mentions=NO_MENTIONS)

    @app_commands.command(name="list", description="Ouvrir tes rappels, tes échecs et ton historique avec les boutons de gestion.")
    async def list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await send_view(interaction, await ReminderDashboard.load(interaction.guild_id, interaction.user.id, guild=interaction.guild))

    @app_commands.command(name="delete", description="Choisir un de tes rappels et confirmer sa suppression.")
    @app_commands.describe(reminder_id="Choisis un rappel proposé, ou saisis son numéro personnel (exemple : #1)")
    async def delete(self, interaction: discord.Interaction, reminder_id: str):
        await interaction.response.defer(ephemeral=True)
        reminder = await resolve_reminder(reminder_id, interaction.guild_id, interaction.user.id)
        if reminder is None:
            raise ValueError(STALE)
        await send_view(interaction, DeleteConfirmation(reminder))

    @app_commands.command(name="reset", description="Annuler tes rappels sur ce serveur et recommencer à #1 (confirmation).")
    async def reset(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        records = await list_reminders(interaction.guild_id, interaction.user.id)
        preferences = await get_preferences(interaction.guild_id, interaction.user.id)
        expected = tuple(sorted((record.id, record.revision, record.status) for record in records))
        await send_view(interaction, ResetConfirmation(interaction.guild_id, interaction.user.id, preferences["generation"], expected))

    @app_commands.command(name="edit", description="Choisir un rappel à modifier avec l'assistant ou les paramètres facultatifs.")
    @app_commands.choices(delivery=_DELIVERY_CHOICES, category=_CATEGORY_CHOICES)
    @app_commands.describe(reminder_id="Choisis un rappel proposé, ou son numéro personnel (#1 ou 1)", when="Nouvelle date ou délai",
        text="Nouveau message", delivery="Nouvelle destination", channel="Nouveau salon", timezone="Fuseau du nouvel horaire",
        mention="Te mentionner lors de l'envoi", recipients="Nouvelles mentions ; aucun pour les retirer (ou utilise l'assistant)",
        category="Nouvelle catégorie")
    async def edit(self, interaction: discord.Interaction, reminder_id: str, when: str | None = None,
                   text: str | None = None, delivery: Delivery | None = None, channel: discord.TextChannel | None = None,
                   timezone: str | None = None, mention: bool | None = None, recipients: str | None = None,
                   category: Category | None = None):
        await interaction.response.defer(ephemeral=True)
        reminder = await resolve_reminder(reminder_id, interaction.guild_id, interaction.user.id)
        if reminder is None:
            raise ValueError(STALE)
        if timezone is not None and when is None:
            raise ValueError("Utilise timezone avec une nouvelle date when. Pour mémoriser ton fuseau, ouvre `/reminder list`.")
        if all(value is None for value in (when, text, delivery, channel, mention, recipients, category, timezone)):
            await send_view(interaction, ReminderEditor(reminder, step=1 if reminder.due_at <= time.time() else 4, editing=True))
            return
        channel_id = destination(interaction, delivery, channel, reminder.channel_id)
        updated = replace(reminder, channel_id=channel_id, message=text if text is not None else reminder.message,
            mention_owner=mention if mention is not None else reminder.mention_owner,
            recipient_ids=parse_recipients(recipients) if recipients is not None else (reminder.recipient_ids if channel_id else ()),
            category=category or reminder.category)
        if when is not None:
            preferences = await get_preferences(interaction.guild_id, interaction.user.id)
            updated = replace(updated, timezone=timezone or preferences["timezone"])
            try:
                updated = replace(updated, due_at=parse_reminder_time(when, updated.timezone))
            except PastTimeError as exc:
                await send_view(interaction, TomorrowChoice(updated, exc.tomorrow, editing=True))
                return
        updated = validate_reminder(updated)
        if updated.due_at <= time.time():
            await send_view(interaction, ReminderEditor(updated, step=1, editing=True))
            return
        await validate_destination(interaction.client, updated)
        if not await edit_reminder(updated):
            raise ValueError(STALE)
        await send_view(interaction, ReminderDetails(replace(updated, status="pending", last_error=None, revision=updated.revision + 1),
                                                    notice="✅ Rappel modifié."))

    @edit.autocomplete("reminder_id")
    @delete.autocomplete("reminder_id")
    async def reminder_choices(self, interaction: discord.Interaction, current: str):
        records = await list_reminders(interaction.guild_id, interaction.user.id)
        query = current.casefold().removeprefix("#")
        choices = []
        for reminder in records:
            if reminder.status == "sending":
                continue
            if query and query not in reminder.message.casefold() and query not in str(reminder.reference):
                continue
            date = datetime.fromtimestamp(reminder.due_at, ZoneInfo(reminder.timezone)).strftime("%d/%m %H:%M")
            choices.append(app_commands.Choice(name=f"#{reminder.reference} · {date} · {reminder.message}"[:100], value=f"r:{reminder.id}"))
        return choices[:25]

    @staticmethod
    def parse_id(value):
        try:
            number = int(value.strip().removeprefix("#"))
            return number if 0 < number < 2**64 else None
        except ValueError:
            return None


async def register(bot):
    bot.tree.add_command(Remind())
