"""Member-owned, private reminder management commands."""

from dataclasses import replace
import time
from typing import Literal

import discord
from discord import app_commands

from src.utils.pagination import PaginationView
from src.utils.reminder_delivery import delivery_error_message, parse_recipients, validate_destination
from src.utils.reminder_time import DEFAULT_TIMEZONE, parse_reminder_time
from src.utils.reminders import (
    CATEGORIES, Reminder, create_reminder, delete_reminder, edit_reminder,
    get_reminder, list_reminders, validate_reminder,
)

Delivery = Literal["dm", "current", "channel"]
Category = Literal["custom", "staff_meeting", "deadline", "ooc_event", "rp_event"]
_NOT_FOUND = "Rappel introuvable, modifié, déjà envoyé ou en cours d'envoi. Utilise `/reminder list`."
_STATUS_LABELS = {"pending": "En attente", "sending": "En cours d'envoi", "sent": "Envoyé", "failed": "Échec"}
_DELIVERY_CHOICES = [
    app_commands.Choice(name="Message privé", value="dm"),
    app_commands.Choice(name="Salon actuel", value="current"),
    app_commands.Choice(name="Salon choisi", value="channel"),
]
_CATEGORY_CHOICES = [app_commands.Choice(name=label, value=value) for value, label in CATEGORIES.items()]


def destination(interaction, delivery: Delivery | None, channel, previous: int | None = None) -> int | None:
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


def summary(reminder: Reminder) -> str:
    target = f"dans <#{reminder.channel_id}>" if reminder.channel_id else "en message privé"
    return f"Rappel **#{reminder.id}** programmé pour le <t:{reminder.due_at}:F> (<t:{reminder.due_at}:R>), {target}."


@app_commands.guild_only()
class Remind(app_commands.Group):
    def __init__(self):
        super().__init__(name="reminder", description="Créer et gérer tes rappels.")

    @app_commands.command(name="create", description="Programmer un rappel ponctuel, envoyé en message privé par défaut.")
    @app_commands.checks.cooldown(3, 60, key=lambda interaction: (interaction.guild_id, interaction.user.id))
    @app_commands.choices(delivery=_DELIVERY_CHOICES, category=_CATEGORY_CHOICES)
    @app_commands.describe(
        when="2h, 1j 30m, demain 18:00, HH:MM ou JJ/MM/AAAA HH:MM",
        text="Le texte de ton rappel (1 000 caractères maximum)",
        delivery="Message privé, salon actuel ou salon choisi",
        channel="Salon textuel de destination ; sélectionne automatiquement l'envoi dans un salon",
        timezone="Fuseau horaire IANA pour les dates et heures (par défaut : Europe/Brussels)",
        mention="Te mentionner lors de l'envoi du rappel",
        recipients="Jusqu'à 10 mentions ou identifiants de membres, séparés par des espaces (salons uniquement)",
        category="Catégorie facultative ; le texte de ton rappel reste libre",
    )
    async def create(self, interaction: discord.Interaction, when: str, text: str,
                     delivery: Delivery | None = None, channel: discord.TextChannel | None = None,
                     timezone: str = DEFAULT_TIMEZONE, mention: bool = True,
                     recipients: str | None = None, category: Category = "custom"):
        await interaction.response.defer(ephemeral=True)
        try:
            reminder = validate_reminder(Reminder(
                guild_id=interaction.guild_id, user_id=interaction.user.id,
                channel_id=destination(interaction, delivery, channel),
                due_at=parse_reminder_time(when, timezone), message=text, category=category,
                mention_owner=mention, recipient_ids=parse_recipients(recipients) if recipients is not None else (),
            ))
            await validate_destination(interaction.client, reminder)
            reminder = replace(reminder, id=await create_reminder(reminder))
        except (ValueError, discord.Forbidden, discord.NotFound) as exc:
            message = str(exc) if isinstance(exc, ValueError) else "Le salon ou le membre sélectionné est indisponible."
            await interaction.followup.send(message, ephemeral=True)
            return
        await interaction.followup.send(summary(reminder), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="list", description="Afficher tes rappels en attente et les échecs d'envoi sur ce serveur.")
    async def list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        reminders = await list_reminders(interaction.guild_id, interaction.user.id)
        if not reminders:
            await interaction.followup.send("Tu n'as aucun rappel actif sur ce serveur.", ephemeral=True)
            return

        def render(page: int) -> discord.Embed:
            embed = discord.Embed(title="Tes rappels", color=discord.Color.blurple())
            for reminder in reminders[(page - 1) * 5:page * 5]:
                target = f"<#{reminder.channel_id}>" if reminder.channel_id else "Message privé"
                text = discord.utils.escape_markdown(reminder.message[:200])
                ids = list(reminder.recipient_ids)
                if reminder.mention_owner and reminder.user_id not in ids:
                    ids.insert(0, reminder.user_id)
                mentions = " ".join(f"<@{user_id}>" for user_id in ids) or "Aucune"
                value = f"<t:{reminder.due_at}:F> · {target}\n{text}\nMentions : {mentions}"
                if reminder.last_error:
                    value += f"\n{delivery_error_message(reminder.last_error)}"
                embed.add_field(
                    name=f"#{reminder.id} · {CATEGORIES[reminder.category]} · {_STATUS_LABELS[reminder.status]}",
                    value=value, inline=False,
                )
            embed.set_footer(text="Utilise /reminder edit ou /reminder delete avec l'identifiant du rappel.")
            return embed

        view = PaginationView(interaction.user.id, (len(reminders) + 4) // 5, render)
        view.message = await interaction.followup.send(
            embed=view.current_embed(), view=view, ephemeral=True, wait=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="delete", description="Supprimer l'un de tes rappels en attente ou en échec.")
    @app_commands.describe(reminder_id="L'identifiant du rappel affiché par /reminder list")
    async def delete(self, interaction: discord.Interaction, reminder_id: str):
        await interaction.response.defer(ephemeral=True)
        parsed_id = self.parse_id(reminder_id)
        deleted = parsed_id is not None and await delete_reminder(parsed_id, interaction.guild_id, interaction.user.id)
        await interaction.followup.send("Rappel supprimé." if deleted else _NOT_FOUND, ephemeral=True)

    @app_commands.command(name="edit", description="Modifier l'un de tes rappels en attente ou en échec.")
    @app_commands.choices(delivery=_DELIVERY_CHOICES, category=_CATEGORY_CHOICES)
    @app_commands.describe(
        reminder_id="L'identifiant du rappel affiché par /reminder list",
        when="Nouvelle date : 2h, demain 18:00, HH:MM ou JJ/MM/AAAA HH:MM",
        text="Le nouveau texte libre du rappel",
        delivery="Changer le mode d'envoi ; le message privé retire les destinataires supplémentaires",
        channel="Le nouveau salon textuel de destination",
        timezone="Fuseau horaire IANA utilisé pour la nouvelle date (par défaut : Europe/Brussels)",
        mention="Te mentionner lors de l'envoi du rappel",
        recipients="Nouvelles mentions ou identifiants de membres ; 'aucun' pour retirer les destinataires",
        category="Changer la catégorie du rappel",
    )
    async def edit(self, interaction: discord.Interaction, reminder_id: str, when: str | None = None,
                   text: str | None = None, delivery: Delivery | None = None,
                   channel: discord.TextChannel | None = None, timezone: str = DEFAULT_TIMEZONE,
                   mention: bool | None = None, recipients: str | None = None, category: Category | None = None):
        await interaction.response.defer(ephemeral=True)
        parsed_id = self.parse_id(reminder_id)
        reminder = await get_reminder(parsed_id, interaction.guild_id, interaction.user.id) if parsed_id else None
        if reminder is None:
            await interaction.followup.send(_NOT_FOUND, ephemeral=True)
            return
        try:
            if all(value is None for value in (when, text, delivery, channel, mention, recipients, category)):
                raise ValueError("Indique au moins un champ à modifier.")
            channel_id = destination(interaction, delivery, channel, reminder.channel_id)
            recipient_ids = reminder.recipient_ids if channel_id is not None else ()
            if recipients is not None:
                recipient_ids = parse_recipients(recipients)
            updated = validate_reminder(replace(
                reminder, channel_id=channel_id,
                due_at=parse_reminder_time(when, timezone) if when is not None else reminder.due_at,
                message=text if text is not None else reminder.message,
                mention_owner=mention if mention is not None else reminder.mention_owner,
                recipient_ids=recipient_ids, category=category if category is not None else reminder.category,
            ))
            if updated.due_at <= time.time():
                raise ValueError("Indique une nouvelle date dans le futur avec l'option when.")
            await validate_destination(interaction.client, updated)
            saved = await edit_reminder(updated)
        except (ValueError, discord.Forbidden, discord.NotFound) as exc:
            message = str(exc) if isinstance(exc, ValueError) else "Le salon ou le membre sélectionné est indisponible."
            await interaction.followup.send(message, ephemeral=True)
            return
        await interaction.followup.send(
            summary(updated) if saved else _NOT_FOUND, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    @staticmethod
    def parse_id(value: str) -> int | None:
        try:
            number = int(value)
            return number if 0 < number < 2**64 else None
        except ValueError:
            return None


async def register(bot):
    bot.tree.add_command(Remind())
