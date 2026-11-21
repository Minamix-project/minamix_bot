"""English ticket commands and a persistent French support panel."""

from datetime import timezone
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from src.config import GUILD_IDS
from src.utils.embed import set_bot_footer
from src.utils.views import ExpiringView
from src.utils.ticket_errors import send_error
from src.utils.ticket_controls import TicketCloseView, show_delete_confirmation
from src.utils.permissions import is_admin
from src.utils.ticket_service import NO_MENTIONS, TicketService, require_access, transcript_file
from src.utils.ticket_setup import SetupContext, SetupHome
from src.utils.tickets import CATEGORY_OPTIONS, TicketError, record_staff_message, ticket_session
from src.utils.ticket_categories import CategoryEditor

logger = logging.getLogger(__name__)


class TicketPanel(discord.ui.View):
    def __init__(self, service, categories=None):
        super().__init__(timeout=None)
        self.service = service
        select = discord.ui.Select(
            custom_id="aurum:tickets:category:v1",
            placeholder="Choisis le type de demande…",
            options=[
                discord.SelectOption(label=option.label, value=value, emoji=option.emoji, description=option.description)
                for value, option in CATEGORY_OPTIONS.items()
            ],
        )
        select.callback = self.choose
        self.add_item(select)
        self.set_categories(categories if categories is not None else [
            {"category_key": key, "name": option.label, "emoji": option.emoji, "description": option.description}
            for key, option in CATEGORY_OPTIONS.items()
        ])

    def set_categories(self, categories):
        self.categories = tuple(categories)
        self.children[0].options = [
            discord.SelectOption(label=category["name"], value=category["category_key"],
                                 emoji=category["emoji"], description=category["description"])
            for category in categories
        ] or [discord.SelectOption(label="Aucune catégorie disponible", value="unavailable")]
        self.children[0].disabled = not self.categories
        self.children[0].placeholder = "Choisis le type de demande…" if self.categories else "Aucune catégorie disponible"

    async def interaction_check(self, interaction):
        if interaction.guild_id in GUILD_IDS and isinstance(interaction.user, discord.Member):
            return True
        await interaction.response.send_message("❌ Ce panneau n'est pas disponible ici.", ephemeral=True)
        return False

    async def choose(self, interaction):
        category = interaction.data["values"][0]
        # A fresh menu clears the client selection even when ticket creation is rejected.
        await interaction.response.edit_message(view=TicketPanel(self.service, self.categories))
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

    @app_commands.command(
        name="panel", description="Ouvrir l'assistant de création et de gestion des panneaux de tickets."
    )
    @app_commands.check(lambda interaction: is_admin(interaction.user))
    async def panel(self, interaction: discord.Interaction):
        context = SetupContext(
            self.service, lambda: TicketPanel(self.service), send_error, interaction.user.id, interaction.guild_id
        )
        view = SetupHome(context)
        await interaction.response.send_message(
            embed=view.embed(interaction), view=view, ephemeral=True, allowed_mentions=NO_MENTIONS
        )
        view.message = await interaction.original_response()

    @app_commands.command(name="create", description="Créer un ticket de support sans passer par le panneau.")
    @app_commands.describe(
        reason="Type de demande",
        user="Membre pour lequel ouvrir le ticket (administration uniquement)",
        panel="Panneau à utiliser si plusieurs sont disponibles ; facultatif sinon",
    )
    async def create(
        self, interaction: discord.Interaction, reason: str, user: discord.Member | None = None, panel: str | None = None
    ):
        await interaction.response.defer(ephemeral=True)
        if panel is not None and (not panel.isascii() or not panel.isdecimal() or len(panel) > 20):
            raise TicketError("Choisis un panneau proposé dans la liste du paramètre `panel`.")
        ticket = await self.service.create(
            interaction, reason, direct=True, user=user, panel_id=int(panel) if panel is not None else None
        )
        label = "Ton ticket a été créé" if ticket.creator_id == interaction.user.id else "Le ticket du membre a été créé"
        await interaction.followup.send(
            f"✅ {label} : <#{ticket.channel_id}>.", ephemeral=True, allowed_mentions=NO_MENTIONS
        )

    @app_commands.command(name="categories", description="Créer, supprimer et personnaliser les catégories de tickets.")
    @app_commands.check(lambda interaction: is_admin(interaction.user))
    async def categories(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        context = SetupContext(
            self.service, lambda: TicketPanel(self.service), send_error, interaction.user.id, interaction.guild_id,
        )
        view = CategoryEditor(context, await self.service.categories(interaction))
        view.build(interaction.guild)
        view.message = await interaction.followup.send(
            embed=view.embed(interaction), view=view, ephemeral=True, wait=True, allowed_mentions=NO_MENTIONS,
        )

    @create.autocomplete("reason")
    async def create_reason_choices(self, interaction: discord.Interaction, current: str):
        if interaction.guild_id not in GUILD_IDS or not isinstance(interaction.user, discord.Member):
            return []
        try:
            categories = await self.service.categories(interaction)
        except TicketError:
            return []
        query = current.casefold()
        return [
            app_commands.Choice(name=f"{category['emoji']} {category['name']}"[:100], value=category["category_key"])
            for category in categories if query in category["name"].casefold() or query in category["category_key"]
        ][:25]

    @create.autocomplete("panel")
    async def create_panel_choices(self, interaction: discord.Interaction, current: str):
        if interaction.guild_id not in GUILD_IDS or not isinstance(interaction.user, discord.Member):
            return []
        try:
            panels = await self.service.creation_panels(interaction)
        except TicketError:
            # Autocomplete cannot display the normal private validation reply.
            return []
        query = current.casefold()
        return [
            app_commands.Choice(name=f"[{panel['id']}] {panel['name']}"[:100], value=str(panel["id"]))
            for panel in panels if query in panel["name"].casefold() or query in str(panel["id"])
        ][:25]

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

    @app_commands.command(name="delete", description="Supprimer ce ticket en conservant ses archives (personnel, confirmation).")
    async def delete(self, interaction: discord.Interaction):
        await show_delete_confirmation(self.service, interaction)

    @app_commands.command(name="claim", description="Prendre en charge ce ticket (support de la catégorie ou administration).")
    async def claim(self, interaction: discord.Interaction):
        await self.assignment(interaction, release=False)

    @app_commands.command(name="release", description="Libérer ce ticket (responsable actuel ou administration).")
    async def release(self, interaction: discord.Interaction):
        await self.assignment(interaction, release=True)

    @app_commands.command(name="emoji", description="Définir ton emoji personnel pour les tickets pris en charge.")
    @app_commands.describe(emoji="Ton emoji Unicode ; laisse vide pour revenir à la pastille verte")
    async def emoji(self, interaction: discord.Interaction, emoji: app_commands.Range[str, 1, 32] | None = None):
        await interaction.response.defer(ephemeral=True)
        selected = await self.service.set_staff_emoji(interaction, emoji)
        text = f"Ton emoji de prise en charge est maintenant {selected}." if emoji is not None else "Ton emoji a été réinitialisé à 🟢."
        await interaction.followup.send(f"✅ {text}", ephemeral=True, allowed_mentions=NO_MENTIONS)

    async def assignment(self, interaction, *, release):
        await interaction.response.defer(ephemeral=True)
        await self.service.assign(interaction, release=release)
        text = "Tu as libéré le ticket." if release else "Tu prends maintenant ce ticket en charge."
        await interaction.followup.send(f"✅ {text}", ephemeral=True, allowed_mentions=NO_MENTIONS)

    @app_commands.command(name="transcript", description="Télécharger l'historique du ticket (créateur ou personnel).")
    async def transcript(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket, content = await self.service.transcript(interaction)
        await interaction.followup.send(
            f"📄 Historique du ticket #{ticket.reference}.",
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
            embed = discord.Embed(title=f"Ticket #{ticket.reference}", color=discord.Color.blurple())
            embed.add_field(name="Créateur", value=f"<@{ticket.creator_id}> (`{ticket.creator_id}`)")
            embed.add_field(name="Catégorie", value=ticket.label)
            embed.add_field(name="État", value="Ouvert" if ticket.status == "open" else "Fermé")
            embed.add_field(name="Responsable", value=f"<@{ticket.claimed_by}>" if ticket.claimed_by else "Aucun")
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

    @app_commands.command(
        name="purge", description="Supprimer tous les tickets du serveur et repartir à 0001 (confirmation)."
    )
    @app_commands.check(lambda interaction: is_admin(interaction.user))
    async def purge(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        expected_ids = await self.service.purge_preview(interaction)
        embed = discord.Embed(
            title="⚠️ Purger tous les tickets ?",
            description=f"**{len(expected_ids)} ticket(s)** sur ce serveur.\n\n"
            "Cette action supprimera définitivement les salons de tickets, leurs données, les interventions, "
            "l'historique des actions, les transcripts et l'historique des messages conservé en base pour ces salons.\n"
            "Le prochain ticket sera **ticket-0001**. Les panneaux restent en place.\n\n"
            "Les copies déjà envoyées dans les logs Discord, téléchargées et présentes dans les sauvegardes "
            "ne sont pas supprimées. Une trace de la purge restera dans le journal d'audit.\n\n"
            "**Cette suppression est irréversible.**",
            color=discord.Color.red(),
        )
        set_bot_footer(embed, interaction)
        view = TicketPurgeConfirmation(self.service, interaction.user.id, interaction.guild_id, expected_ids)
        view.message = await interaction.followup.send(
            embed=embed, view=view, ephemeral=True, wait=True, allowed_mentions=NO_MENTIONS
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
            warning = await self.service.send_transcript(interaction.guild, ticket, content)
            if warning:
                message += "\n" + warning
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=NO_MENTIONS)


class TicketPurgeConfirmation(ExpiringView):
    def __init__(self, service, owner_id, guild_id, expected_ids):
        super().__init__(timeout=60, owner_id=owner_id)
        self.service = service
        self.guild_id = guild_id
        self.expected_ids = expected_ids
        self.used = False

    async def interaction_check(self, interaction):
        if not await super().interaction_check(interaction):
            return False
        if interaction.guild_id != self.guild_id or not is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ Tu dois toujours avoir les droits d'administration sur ce serveur.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Supprimer tous les tickets", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.used or self.is_finished():
            await interaction.response.send_message(
                "Cette confirmation a déjà été utilisée ou a expiré.", ephemeral=True
            )
            return
        if not await self.interaction_check(interaction):
            return
        self.used = True
        self.stop()
        await interaction.response.edit_message(content="⏳ Suppression des tickets en cours…", embed=None, view=None)
        count = await self.service.purge(interaction, self.expected_ids)
        await interaction.edit_original_response(
            content=f"✅ {count} ticket(s) supprimé(s), historiques et transcripts effacés. Le prochain ticket sera **ticket-0001**.",
            embed=None,
            view=None,
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.used or self.is_finished():
            return
        if not await self.interaction_check(interaction):
            return
        self.used = True
        self.stop()
        await interaction.response.edit_message(
            content="✅ Purge annulée. Aucun ticket n'a été supprimé.", embed=None, view=None
        )

    async def on_error(self, interaction, error, item):
        if self.used:
            await interaction.edit_original_response(
                content="❌ Purge interrompue. Consulte le détail ci-dessous.", embed=None, view=None
            )
        await send_error(interaction, error)


class TicketActivity(commands.Cog):
    def __init__(self, bot, service):
        self.bot = bot
        self.service = service
        self._synchronizing = False
        self._panels_refreshed = set()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.retry_sync.is_running():
            self.retry_sync.start()

    @tasks.loop(minutes=1)
    async def retry_sync(self):
        await self.bot.wait_until_ready()
        try:
            await self.synchronize()
        except Exception:
            logger.exception("Ticket synchronization failed; will retry")

    @retry_sync.before_loop
    async def wait_for_ready(self):
        await self.bot.wait_until_ready()

    async def synchronize(self):
        if self._synchronizing:
            return
        self._synchronizing = True
        try:
            for guild_id in GUILD_IDS:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    try:
                        await self.service.sync_categories(guild)
                        await self.service.normalize_channel_names(guild)
                        if guild_id not in self._panels_refreshed:
                            await self.service.refresh_panel_menus(guild, lambda: TicketPanel(self.service))
                            self._panels_refreshed.add(guild_id)
                    except (TicketError, discord.HTTPException, discord.RateLimited):
                        logger.warning("Ticket synchronization deferred guild=%s", guild_id)
        finally:
            self._synchronizing = False

    async def cog_unload(self):
        task = self.retry_sync.get_task()
        self.retry_sync.cancel()
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None or message.guild.id not in GUILD_IDS or message.author.bot:
            return
        if isinstance(message.author, discord.Member):
            await record_staff_message(message.guild.id, message.channel.id, message.author)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        if (after.guild.id in GUILD_IDS
                and (before.permissions.manage_guild != after.permissions.manage_guild
                     or before.permissions.administrator != after.permissions.administrator)):
            await self.synchronize()

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        if role.guild.id in GUILD_IDS and (role.permissions.manage_guild or role.permissions.administrator):
            await self.synchronize()


async def register(bot):
    service = TicketService()
    bot.tree.add_command(Tickets(service))
    bot.add_view(TicketPanel(service))
    bot.add_view(TicketCloseView(service))
    await bot.add_cog(TicketActivity(bot, service))
