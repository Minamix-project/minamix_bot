"""Restart-safe background delivery for persistent one-time reminders."""

import asyncio
import logging
import time

import discord
from discord.ext import commands, tasks

from src.config import GUILD_IDS
from src.utils.error_reporting import report_error
from src.utils.reminder_delivery import delivery_error_message, send_reminder
from src.utils.reminders import (
    MAX_ATTEMPTS, claim_next_reminder, finish_reminder, purge_finished_reminders,
)

logger = logging.getLogger(__name__)


async def deliver_claimed_reminder(bot, reminder) -> None:
    try:
        if reminder.attempts > MAX_ATTEMPTS:
            raise ValueError(delivery_error_message("Delivery was interrupted too many times. Edit this reminder to retry."))
        async with asyncio.timeout(60):
            await send_reminder(bot, reminder)
    except (ValueError, discord.Forbidden, discord.NotFound) as exc:
        detail = delivery_error_message(
            str(exc) if isinstance(exc, ValueError) else "Discord denied delivery or the destination was removed."
        )
        await finish_reminder(reminder, int(time.time()), error=detail, permanent=True)
        await notify_failure(bot, reminder)
    except Exception as exc:
        # Do not persist raw API responses or reminder contents in error fields.
        await finish_reminder(
            reminder, int(time.time()),
            error=delivery_error_message("Temporary delivery failure. Please try again later."),
        )
        await report_error(bot, guild_ids=reminder.guild_id, source=f"reminder:{reminder.id}", error=exc)
        if reminder.attempts >= MAX_ATTEMPTS:
            await notify_failure(bot, reminder)
    else:
        await finish_reminder(reminder, int(time.time()))


async def notify_failure(bot, reminder) -> None:
    try:
        user = bot.get_user(reminder.user_id) or await bot.fetch_user(reminder.user_id)
        await user.send(
            f"Le rappel #{reminder.id} n'a pas pu être envoyé. "
            "Utilise `/reminder list` sur le serveur d'origine pour connaître la raison, puis modifie ou supprime le rappel.",
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException:
        logger.info("Could not notify the owner of failed reminder %s", reminder.id)


class ReminderDelivery(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_cleanup = 0
        self.deliver.start()

    async def cog_unload(self):
        task = self.deliver.get_task()
        self.deliver.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    @tasks.loop(seconds=15)
    async def deliver(self):
        try:
            for _ in range(25):
                reminder = await claim_next_reminder(int(time.time()), GUILD_IDS)
                if reminder is None:
                    break
                try:
                    await deliver_claimed_reminder(self.bot, reminder)
                except Exception:
                    # A database failure leaves the lease recoverable. One bad
                    # reminder must not stop the worker permanently.
                    logger.exception("Could not finalize reminder %s", reminder.id)
            now = int(time.time())
            if now - self._last_cleanup >= 3600:
                await purge_finished_reminders(now)
                self._last_cleanup = now
        except Exception:
            logger.exception("Reminder polling failed; the next poll will retry")

    @deliver.before_loop
    async def before_deliver(self):
        await self.bot.wait_until_ready()


async def register(bot):
    await bot.add_cog(ReminderDelivery(bot))
