"""Member-owned, private reminder management commands."""

from dataclasses import replace
import time
from typing import Literal

import discord
from discord import app_commands

from src.utils.pagination import PaginationView
from src.utils.reminder_delivery import parse_recipients, validate_destination
from src.utils.reminder_time import DEFAULT_TIMEZONE, parse_reminder_time
from src.utils.reminders import (
    CATEGORIES, Reminder, create_reminder, delete_reminder, edit_reminder,
    get_reminder, list_reminders, validate_reminder,
)

Delivery = Literal["dm", "current", "channel"]
Category = Literal["custom", "staff_meeting", "deadline", "ooc_event", "rp_event"]
_NOT_FOUND = "Reminder unavailable, changed, already delivered, or currently being sent. Use `/remind list`."


def destination(interaction, delivery: Delivery | None, channel, previous: int | None = None) -> int | None:
    if channel is not None:
        if delivery not in {None, "channel"}:
            raise ValueError("Use channel delivery when selecting a destination channel.")
        return channel.id
    if delivery == "channel":
        raise ValueError("Select a destination using the channel option.")
    if delivery == "dm":
        return None
    if delivery == "current":
        if not isinstance(interaction.channel, discord.TextChannel):
            raise ValueError("Select a server text channel using the channel option.")
        return interaction.channel_id
    return previous


def summary(reminder: Reminder) -> str:
    target = f"<#{reminder.channel_id}>" if reminder.channel_id else "a DM to you"
    return f"Reminder **#{reminder.id}** scheduled for <t:{reminder.due_at}:F> (<t:{reminder.due_at}:R>) in {target}."


@app_commands.guild_only()
class Remind(app_commands.Group):
    def __init__(self):
        super().__init__(name="remind", description="Create and manage your reminders.")

    @app_commands.command(name="create", description="Schedule a one-time reminder. Delivery defaults to DM.")
    @app_commands.checks.cooldown(3, 60, key=lambda interaction: (interaction.guild_id, interaction.user.id))
    @app_commands.describe(
        when="2h, 1d 30m, tomorrow 18:00, HH:MM, or DD/MM/YYYY HH:MM",
        text="Your reminder text (up to 1,000 characters)",
        delivery="DM to you, current text channel, or a chosen channel",
        channel="Destination text channel; implies channel delivery when delivery is omitted",
        timezone="IANA timezone for dates and times (default: Europe/Brussels)",
        mention="Mention yourself when the reminder is delivered",
        recipients="Up to 10 additional member mentions or IDs, separated by spaces (channels only)",
        category="Optional preset label; your reminder text is always free-form",
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
            message = str(exc) if isinstance(exc, ValueError) else "The selected destination or member is unavailable."
            await interaction.followup.send(message, ephemeral=True)
            return
        await interaction.followup.send(summary(reminder), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="list", description="List your pending reminders and delivery failures in this server.")
    async def list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        reminders = await list_reminders(interaction.guild_id, interaction.user.id)
        if not reminders:
            await interaction.followup.send("You have no active reminders in this server.", ephemeral=True)
            return

        def render(page: int) -> discord.Embed:
            embed = discord.Embed(title="Your reminders", color=discord.Color.blurple())
            for reminder in reminders[(page - 1) * 5:page * 5]:
                target = f"<#{reminder.channel_id}>" if reminder.channel_id else "DM"
                text = discord.utils.escape_markdown(reminder.message[:200])
                ids = list(reminder.recipient_ids)
                if reminder.mention_owner and reminder.user_id not in ids:
                    ids.insert(0, reminder.user_id)
                mentions = " ".join(f"<@{user_id}>" for user_id in ids) or "None"
                value = f"<t:{reminder.due_at}:F> · {target}\n{text}\nMentions: {mentions}"
                if reminder.last_error:
                    value += f"\n{reminder.last_error}"
                embed.add_field(
                    name=f"#{reminder.id} · {CATEGORIES[reminder.category]} · {reminder.status}",
                    value=value, inline=False,
                )
            embed.set_footer(text="Use /remind edit or /remind delete with a reminder ID.")
            return embed

        view = PaginationView(interaction.user.id, (len(reminders) + 4) // 5, render)
        view.message = await interaction.followup.send(
            embed=view.current_embed(), view=view, ephemeral=True, wait=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="delete", description="Delete one of your pending or failed reminders.")
    @app_commands.describe(reminder_id="The reminder ID shown by /remind list")
    async def delete(self, interaction: discord.Interaction, reminder_id: str):
        await interaction.response.defer(ephemeral=True)
        parsed_id = self.parse_id(reminder_id)
        deleted = parsed_id is not None and await delete_reminder(parsed_id, interaction.guild_id, interaction.user.id)
        await interaction.followup.send("Reminder deleted." if deleted else _NOT_FOUND, ephemeral=True)

    @app_commands.command(name="edit", description="Edit one of your pending or failed reminders.")
    @app_commands.describe(
        reminder_id="The reminder ID shown by /remind list",
        when="New schedule: 2h, tomorrow 18:00, HH:MM, or DD/MM/YYYY HH:MM",
        text="New free-form reminder text",
        delivery="Change delivery mode; switching to DM clears additional recipients",
        channel="New destination text channel",
        timezone="IANA timezone used only when changing the schedule (default: Europe/Brussels)",
        mention="Whether to mention yourself",
        recipients="New member mentions or IDs; use 'none' to clear additional recipients",
        category="Change the preset label",
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
                raise ValueError("Provide at least one field to change.")
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
                raise ValueError("Set a new future schedule using the when option.")
            await validate_destination(interaction.client, updated)
            saved = await edit_reminder(updated)
        except (ValueError, discord.Forbidden, discord.NotFound) as exc:
            message = str(exc) if isinstance(exc, ValueError) else "The selected destination or member is unavailable."
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
