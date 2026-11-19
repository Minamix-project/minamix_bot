"""Persistent ticket claiming and creator-only closing controls."""

import discord

from src.config import GUILD_IDS
from src.utils.ticket_errors import send_error
from src.utils.views import ExpiringView


def ticket_embed(bot_user, *, title, description):
    embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
    embed.set_footer(text=bot_user.name, icon_url=bot_user.display_avatar.url)
    return embed


class TicketCloseView(discord.ui.View):
    def __init__(self, service, ticket=None):
        super().__init__(timeout=None)
        self.service = service
        if ticket is not None:
            self.close.disabled = ticket.status != "open"
            self.claim.disabled = ticket.status != "open" or ticket.claimed_by is not None
            if not ticket.claim_enabled:
                self.remove_item(self.claim)
            if ticket.claimed_by is None:
                self.remove_item(self.release)

    async def interaction_check(self, interaction):
        if interaction.guild_id in GUILD_IDS and isinstance(interaction.user, discord.Member):
            return True
        await interaction.response.send_message("❌ Ce bouton n'est pas disponible ici.", ephemeral=True)
        return False

    @discord.ui.button(
        label="Fermer le ticket", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="aurum:tickets:close:v1"
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket = await self.service.creator_ticket(interaction)
        embed = ticket_embed(
            interaction.client.user, title="Fermer le ticket ?", description="Es-tu sûr de vouloir fermer ce ticket ?"
        )
        view = TicketCloseConfirmation(self.service, ticket.creator_id, ticket.guild_id, ticket.channel_id, ticket.id)
        view.message = await interaction.followup.send(
            embed=embed, view=view, ephemeral=True, wait=True, allowed_mentions=discord.AllowedMentions.none()
        )

    @discord.ui.button(
        label="Prendre en charge", emoji="🟢", style=discord.ButtonStyle.success, custom_id="aurum:tickets:claim:v1",
    )
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.assignment(interaction, release=False)

    @discord.ui.button(
        label="Libérer le ticket", emoji="↩️", style=discord.ButtonStyle.secondary, custom_id="aurum:tickets:release:v1",
    )
    async def release(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.assignment(interaction, release=True)

    async def assignment(self, interaction, *, release):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.service.assign(interaction, release=release)
        text = "Tu as libéré le ticket." if release else "Tu prends maintenant ce ticket en charge."
        await interaction.followup.send(f"✅ {text}", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def on_error(self, interaction, error, item):
        await send_error(interaction, error)


def previous_ticket_controls(service, message):
    """Restore the message's previous button layout with live persistent callbacks."""
    buttons = {
        item.custom_id: item.disabled
        for row in getattr(message, "components", ()) for item in row.children
        if isinstance(item, discord.Button)
    }
    view = TicketCloseView(service)
    for item in list(view.children):
        if item.custom_id not in buttons:
            view.remove_item(item)
        else:
            item.disabled = buttons[item.custom_id]
    return view


class TicketCloseConfirmation(ExpiringView):
    def __init__(self, service, creator_id, guild_id, channel_id, ticket_id):
        super().__init__(timeout=60, owner_id=creator_id)
        self.service = service
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.ticket_id = ticket_id
        self.used = False

    async def interaction_check(self, interaction):
        if not await super().interaction_check(interaction):
            return False
        if (
            interaction.guild_id not in GUILD_IDS
            or interaction.guild_id != self.guild_id
            or interaction.channel_id != self.channel_id
        ):
            await interaction.response.send_message("❌ Cette confirmation ne concerne pas ce ticket.", ephemeral=True)
            return False
        if self.used or self.is_finished():
            await interaction.response.send_message(
                "Cette confirmation a déjà été utilisée ou a expiré.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.interaction_check(interaction):
            return
        self.used = True
        self.stop()
        await interaction.response.edit_message(content="⏳ Fermeture du ticket en cours…", embed=None, view=None)
        ticket, content = await self.service.mutate(
            interaction,
            "closed",
            reason="Fermeture demandée par le créateur via le bouton.",
            creator_only=True,
            expected_ticket_id=self.ticket_id,
        )
        warning = await self.service.send_transcript(interaction.guild, ticket, content)
        message = "✅ Ton ticket est fermé. L'historique a été sauvegardé."
        if warning:
            message += "\n" + warning
        await interaction.edit_original_response(
            content=message, embed=None, view=None, allowed_mentions=discord.AllowedMentions.none()
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.interaction_check(interaction):
            return
        self.used = True
        self.stop()
        await interaction.response.edit_message(content="✅ Fermeture annulée.", embed=None, view=None)

    async def on_error(self, interaction, error, item):
        if self.used:
            await interaction.edit_original_response(
                content="❌ Opération interrompue. Consulte le détail ci-dessous.", embed=None, view=None
            )
        await send_error(interaction, error)
