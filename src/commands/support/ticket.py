"""English ticket commands and a persistent French support panel."""

from datetime import timezone

import discord
from discord import app_commands
from discord.ext import commands

from src.config import GUILD_IDS
from src.utils.error_reporting import report_error
from src.utils.permissions import is_admin
from src.utils.ticket_service import NO_MENTIONS, TicketService, require_access, transcript_file
from src.utils.tickets import CATEGORIES, TicketError, record_staff_message, ticket_session


async def send_error(interaction, error):
    if isinstance(error, app_commands.CommandInvokeError):
        error = error.original
    if isinstance(error, TicketError):
        message = f"❌ {error}"
    elif isinstance(error, app_commands.CheckFailure):
        message = "❌ Cette action est réservée à l'administration du serveur."
    elif isinstance(error, discord.Forbidden):
        message = "❌ Discord refuse cette action. Vérifie les permissions du bot dans le salon et la catégorie."
    elif isinstance(error, discord.HTTPException):
        message = "❌ Discord n'a pas pu terminer cette action. Vérifie le ticket avant de réessayer."
    else:
        reference = await report_error(
            interaction.client, guild_ids=interaction.guild_id, source="ticket", error=error, user=interaction.user
        )
        message = f"❌ Une erreur est survenue. Référence : `{reference}`"
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=NO_MENTIONS)
    else:
        await interaction.response.send_message(message, ephemeral=True, allowed_mentions=NO_MENTIONS)


class TicketPanel(discord.ui.View):
    def __init__(self, service):
        super().__init__(timeout=None)
        self.service = service
        select = discord.ui.Select(
            custom_id="aurum:tickets:category:v1",
            placeholder="Choisis le type de demande…",
            options=[discord.SelectOption(label=label, value=value) for value, label in CATEGORIES.items()],
        )
        select.callback = self.choose
        self.add_item(select)

    async def interaction_check(self, interaction):
        if interaction.guild_id in GUILD_IDS and isinstance(interaction.user, discord.Member):
            return True
        await interaction.response.send_message("❌ Ce panneau n'est pas disponible ici.", ephemeral=True)
        return False

    async def choose(self, interaction):
        category = interaction.data["values"][0]
        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket = await self.service.create(interaction, category)
        await interaction.followup.send(
            f"✅ Ton ticket a été créé : <#{ticket.channel_id}>.", ephemeral=True, allowed_mentions=NO_MENTIONS
        )

    async def on_error(self, interaction, error, item):
        await send_error(interaction, error)


@app_commands.guild_only()
class Tickets(app_commands.Group):
    def __init__(self, service):
        super().__init__(name="ticket", description="Créer et gérer les tickets de support.")
        self.service = service

    async def interaction_check(self, interaction):
        if interaction.guild_id not in GUILD_IDS:
            raise TicketError("Ce bot n'est pas disponible sur ce serveur.")
        return True

    async def on_error(self, interaction, error):
        await send_error(interaction, error)

    @app_commands.command(name="panel", description="Créer ou modifier le panneau de support (administration).")
    @app_commands.check(lambda interaction: is_admin(interaction.user))
    @app_commands.describe(
        channel="Salon du panneau",
        category="Catégorie Discord des salons privés",
        staff_role="Rôle du personnel de support",
        logs_channel="Salon privé pour les transcripts",
    )
    async def panel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        category: discord.CategoryChannel,
        staff_role: discord.Role,
        logs_channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        await self.service.panel(interaction, channel, category, staff_role, logs_channel, TicketPanel(self.service))
        await interaction.followup.send(
            f"✅ Panneau de support configuré dans {channel.mention}.", ephemeral=True, allowed_mentions=NO_MENTIONS
        )

    @app_commands.command(name="add", description="Ajouter un membre au ticket (personnel autorisé).")
    @app_commands.describe(user="Membre à ajouter au ticket")
    async def add(self, interaction: discord.Interaction, user: discord.Member):
        await self.change(interaction, "added", user=user)

    @app_commands.command(name="remove", description="Retirer un membre du ticket (personnel autorisé).")
    @app_commands.describe(user="Membre à retirer du ticket")
    async def remove(self, interaction: discord.Interaction, user: discord.Member):
        await self.change(interaction, "removed", user=user)

    @app_commands.command(name="rename", description="Renommer le salon du ticket (personnel autorisé).")
    @app_commands.describe(name="Nouveau nom du salon (90 caractères maximum)")
    async def rename(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 90]):
        await self.change(interaction, "renamed", name=name)

    @app_commands.command(
        name="close", description="Fermer le ticket et sauvegarder son historique (créateur ou personnel)."
    )
    @app_commands.describe(reason="Raison de la fermeture (1 000 caractères maximum)")
    async def close(self, interaction: discord.Interaction, reason: app_commands.Range[str, 1, 1000]):
        await self.change(interaction, "closed", reason=reason)

    @app_commands.command(name="reopen", description="Rouvrir un ticket fermé (personnel autorisé).")
    async def reopen(self, interaction: discord.Interaction):
        await self.change(interaction, "reopened")

    @app_commands.command(name="transcript", description="Télécharger l'historique du ticket (créateur ou personnel).")
    async def transcript(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket, content = await self.service.transcript(interaction)
        await interaction.followup.send(
            f"📄 Historique du ticket #{ticket.id}.",
            file=transcript_file(ticket, content),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )

    @app_commands.command(name="link", description="Lier le ticket à un utilisateur concerné (personnel autorisé).")
    @app_commands.describe(user="Utilisateur concerné ; cette liaison ne lui donne pas accès au ticket")
    async def link(self, interaction: discord.Interaction, user: discord.Member):
        await self.change(interaction, "linked", user=user)

    @app_commands.command(name="info", description="Afficher les informations du ticket (créateur ou personnel).")
    async def info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with ticket_session(interaction.guild_id) as session:
            ticket = await session.get(interaction.channel_id)
            staff_access = require_access(interaction, ticket)
            staff, _events = await session.history(ticket)
            embed = discord.Embed(title=f"Ticket #{ticket.id}", color=discord.Color.blurple())
            embed.add_field(name="Créateur", value=f"<@{ticket.creator_id}> (`{ticket.creator_id}`)")
            embed.add_field(name="Catégorie", value=CATEGORIES[ticket.category])
            embed.add_field(name="État", value="Ouvert" if ticket.status == "open" else "Fermé")
            embed.add_field(
                name="Création", value=discord.utils.format_dt(ticket.created_at.replace(tzinfo=timezone.utc))
            )
            staff_text = ", ".join(f"<@{row['user_id']}>" for row in staff)
            embed.add_field(name="Personnel intervenu", value=(staff_text[:1000] or "Aucun"), inline=False)
            if ticket.closed_at:
                embed.add_field(
                    name="Fermeture", value=discord.utils.format_dt(ticket.closed_at.replace(tzinfo=timezone.utc))
                )
                embed.add_field(name="Fermé par", value=f"<@{ticket.closed_by}>")
                embed.add_field(name="Raison de fermeture", value=ticket.close_reason or "—", inline=False)
            if ticket.subject_id and staff_access:
                embed.add_field(name="Utilisateur concerné", value=f"<@{ticket.subject_id}> (`{ticket.subject_id}`)")
                # Existing moderation commands retain their own administrator checks.
                if is_admin(interaction.user):
                    rows = await session.rows(
                        "SELECT COUNT(*) AS total FROM warnings WHERE guild_id = %s AND user_id = %s",
                        (interaction.guild_id, ticket.subject_id),
                    )
                    embed.add_field(
                        name="Modération",
                        value=f"{rows[0]['total']} avertissement(s). "
                        f"Consulte `/warnings user:{ticket.subject_id}` et `/audit commande:ticket`.",
                        inline=False,
                    )
        await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=NO_MENTIONS)

    @app_commands.command(
        name="reconcile", description="Clore l'enregistrement d'un salon de ticket supprimé (administration)."
    )
    @app_commands.check(lambda interaction: is_admin(interaction.user))
    @app_commands.describe(channel_id="Identifiant du salon de ticket supprimé", reason="Raison de la régularisation")
    async def reconcile(
        self, interaction: discord.Interaction, channel_id: str, reason: app_commands.Range[str, 1, 1000]
    ):
        await interaction.response.defer(ephemeral=True)
        if not channel_id.isascii() or not channel_id.isdecimal() or len(channel_id) > 20 or not reason.strip():
            raise TicketError("Indique un identifiant Discord valide et une raison non vide.")
        async with ticket_session(interaction.guild_id) as session:
            ticket = await session.get(int(channel_id))
            if not ticket or ticket.status != "open":
                raise TicketError("Aucun ticket ouvert ne correspond à cet identifiant sur ce serveur.")
            try:
                await interaction.guild.fetch_channel(ticket.channel_id)
            except discord.NotFound:
                pass
            else:
                raise TicketError("Ce salon existe encore. Utilise `/ticket close` dans le ticket.")
            await session.close(ticket, interaction.user.id, reason.strip(), [])
            await session.event(
                ticket, interaction.user.id, "closed", "Salon supprimé : " + reason.strip()[:980], staff=True
            )
        await interaction.followup.send(
            "✅ Enregistrement fermé. Le salon ayant été supprimé, aucun nouvel historique "
            "n'a pu être généré. Les exports déjà sauvegardés sont conservés.",
            ephemeral=True,
        )

    async def change(self, interaction, action, **kwargs):
        await interaction.response.defer(ephemeral=True)
        ticket, content = await self.service.mutate(interaction, action, **kwargs)
        labels = {
            "added": "Membre ajouté au ticket.",
            "removed": "Membre retiré du ticket.",
            "renamed": "Ticket renommé.",
            "closed": "Ticket fermé ; historique sauvegardé.",
            "reopened": "Ticket rouvert.",
            "linked": "Utilisateur lié au ticket ; ses accès sont inchangés.",
        }
        message = f"✅ {labels[action]}"
        if content is not None:
            warning = await self.service.log_close(interaction.guild, ticket, content)
            if warning:
                message += "\n" + warning
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=NO_MENTIONS)


class TicketActivity(commands.Cog):
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None or message.guild.id not in GUILD_IDS or message.author.bot:
            return
        if isinstance(message.author, discord.Member):
            await record_staff_message(message.guild.id, message.channel.id, message.author)


async def register(bot):
    service = TicketService()
    bot.tree.add_command(Tickets(service))
    bot.add_view(TicketPanel(service))
    await bot.add_cog(TicketActivity())
