"""Shared private reminder presentation, session boundaries and error handling."""

import discord

from src.utils.error_reporting import report_error
from src.utils.views import ExpiringView
from src.utils import reminders as store

NO_MENTIONS = discord.AllowedMentions.none()
STALE = "Ce rappel a changé ou n'est plus disponible. Actualise `/reminder`."
STATUSES = {"pending": "⏳ À venir", "sending": "📨 En cours d'envoi", "failed": "❌ Échec", "sent": "✅ Envoyé"}


def reminder_embed(reminder, *, title=None):
    from src.utils.reminder_delivery import delivery_error_message

    embed = discord.Embed(title=title or f"⏰ Rappel #{reminder.reference}", description=reminder.message,
                          color=discord.Color.blurple())
    embed.add_field(name="Quand ?", value=f"<t:{reminder.due_at}:F>\n<t:{reminder.due_at}:R>")
    embed.add_field(name="Destination", value=f"<#{reminder.channel_id}>" if reminder.channel_id else "Message privé")
    ids = list(reminder.recipient_ids)
    if reminder.channel_id and reminder.mention_owner and reminder.user_id not in ids:
        ids.insert(0, reminder.user_id)
    embed.add_field(name="Personnes mentionnées" if reminder.channel_id else "Destinataire",
                    value=(" ".join(f"<@{value}>" for value in ids) or "Aucune") if reminder.channel_id else "Toi uniquement, en message privé",
                    inline=False)
    embed.add_field(name="Catégorie", value=store.CATEGORIES[reminder.category])
    embed.add_field(name="État", value=STATUSES[reminder.status])
    embed.set_footer(text=f"Fuseau : {reminder.timezone} · Numéro personnel à ce serveur")
    if reminder.last_error:
        embed.add_field(name="Pourquoi l'envoi a échoué ?", value=delivery_error_message(reminder.last_error), inline=False)
    return embed


async def ui_error(interaction, error):
    if isinstance(error, ValueError):
        text = str(error)
    elif isinstance(error, (discord.Forbidden, discord.NotFound)):
        text = "Le salon, le membre ou ce rappel n'est plus accessible. Actualise la liste."
    elif isinstance(error, discord.RateLimited):
        text = f"Discord limite temporairement cette action. Réessaie dans {int(error.retry_after) + 1} secondes."
    else:
        reference = await report_error(interaction.client, guild_ids=interaction.guild_id,
                                       source="reminder.component", error=error, user=interaction.user)
        text = f"Une erreur est survenue. Référence : `{reference}`"
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await send(f"❌ {text}", ephemeral=True, allowed_mentions=NO_MENTIONS)


async def present(interaction, view):
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=view.embed(), view=view, allowed_mentions=NO_MENTIONS)
    else:
        await interaction.response.edit_message(content=None, embed=view.embed(), view=view, allowed_mentions=NO_MENTIONS)
    view.message = await interaction.original_response()


async def send_view(interaction, view):
    view.message = await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True, wait=True,
                                                   allowed_mentions=NO_MENTIONS)


class ReminderView(ExpiringView):
    def __init__(self, guild_id, user_id):
        super().__init__(timeout=300, owner_id=user_id)
        self.guild_id = guild_id

    async def interaction_check(self, interaction):
        if not await super().interaction_check(interaction):
            return False
        if interaction.guild_id != self.guild_id or self.is_finished():
            await interaction.response.send_message("Cette session a expiré. Relance `/reminder`.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏱️ Session expirée. Relance `/reminder`.", embed=None, view=None)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction, error, item):
        await ui_error(interaction, error)

    async def move(self, interaction, view):
        await present(interaction, view)
        self.stop()

    def button(self, label, callback, *, style=discord.ButtonStyle.secondary, row=None, disabled=False):
        item = discord.ui.Button(label=label, style=style, row=row, disabled=disabled)
        item.callback = callback
        self.add_item(item)
        return item

    async def current(self, reminder_id, *, revision=None, mutable=True):
        reminder = await store.get_owned_reminder(reminder_id, self.guild_id, self.owner_id, current_only=mutable)
        if reminder is None or (mutable and reminder.status not in {"pending", "failed"}) or (
                revision is not None and reminder.revision != revision):
            raise ValueError(STALE)
        return reminder


class ReminderModal(discord.ui.Modal):
    def __init__(self, parent, *, title):
        super().__init__(title=title, timeout=300)
        self.parent = parent

    async def interaction_check(self, interaction):
        return await self.parent.interaction_check(interaction)

    async def on_error(self, interaction, error):
        await ui_error(interaction, error)
