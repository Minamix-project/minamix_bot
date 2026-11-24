"""Restart-safe, creator-only snooze buttons on delivered reminders."""

import re
import time

import discord

from src.utils.reminders import get_owned_reminder, snooze_reminder
from src.utils.reminder_ui import NO_MENTIONS, ui_error


class SnoozeButton(discord.ui.DynamicItem[discord.ui.Button],
                   template=r"aurum:reminders:snooze:(?P<guild>\d+):(?P<reminder>\d+):(?P<delay>600|3600):v1"):
    def __init__(self, guild_id, reminder_id, delay):
        self.guild_id, self.reminder_id, self.delay = guild_id, reminder_id, delay
        super().__init__(discord.ui.Button(label="Reporter de " + ("10 min" if delay == 600 else "1 heure"),
            style=discord.ButtonStyle.secondary,
            custom_id=f"aurum:reminders:snooze:{guild_id}:{reminder_id}:{delay}:v1"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match["guild"]), int(match["reminder"]), int(match["delay"]))

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            if interaction.guild_id is not None and interaction.guild_id != self.guild_id:
                raise ValueError("Ce bouton appartient à un autre serveur.")
            source = await get_owned_reminder(self.reminder_id, self.guild_id, interaction.user.id, current_only=True)
            if source is None:
                raise ValueError("Ce report est réservé au créateur du rappel et n'est plus disponible après une remise à zéro.")
            from src.utils.reminder_delivery import validate_destination
            await validate_destination(interaction.client, source)
            due_at = int(time.time()) + self.delay
            await snooze_reminder(source, due_at)
            await interaction.followup.send(f"✅ Nouveau rappel programmé pour <t:{due_at}:F> (<t:{due_at}:R>).",
                                              ephemeral=True, allowed_mentions=NO_MENTIONS)
        except Exception as exc:
            await ui_error(interaction, exc)


def snooze_view(reminder):
    view = discord.ui.View(timeout=None)
    for delay in (600, 3600):
        view.add_item(SnoozeButton(reminder.guild_id, reminder.id, delay))
    return view
