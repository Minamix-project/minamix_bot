"""Private, source-permission-aware moderation tools for retained messages."""

import asyncio
from datetime import datetime, timezone
from typing import Literal

import discord
from discord import app_commands

from src.config import GUILD_IDS
from src.utils.audit import record_admin_action
from src.utils.message_history import EVENT_LABELS
from src.utils.message_logs import MessageSnapshot, text_file
from src.utils.permissions import is_admin
from src.utils.views import ExpiringView

SourceChannel = discord.TextChannel | discord.Thread
EventFilter = Literal["changes", "edited", "deleted", "all"]
NO_MENTIONS = discord.AllowedMentions.none()


def is_moderator(interaction) -> bool:
    return bool(interaction.guild_id in GUILD_IDS and (
        is_admin(interaction.user) or interaction.permissions.manage_messages
    ))


async def source_channel(interaction, channel_id: int):
    if not is_moderator(interaction):
        raise app_commands.CheckFailure
    channel = interaction.guild.get_channel_or_thread(channel_id)
    if channel is None:
        try:
            channel = await interaction.guild.fetch_channel(channel_id)
        except discord.HTTPException:
            raise app_commands.CheckFailure from None
    if not isinstance(channel, (discord.TextChannel, discord.Thread)) or channel.guild.id != interaction.guild_id:
        raise app_commands.CheckFailure
    permissions = channel.permissions_for(interaction.user)
    bot_permissions = channel.permissions_for(interaction.guild.me)
    if not (permissions.view_channel and permissions.read_message_history and
            bot_permissions.view_channel and bot_permissions.read_message_history and
            (permissions.manage_messages or is_admin(interaction.user))):
        raise app_commands.CheckFailure
    if isinstance(channel, discord.Thread) and channel.is_private():
        for member, member_permissions in ((interaction.user, permissions), (interaction.guild.me, bot_permissions)):
            if not member_permissions.manage_threads:
                try:
                    await channel.fetch_member(member.id)
                except discord.HTTPException:
                    raise app_commands.CheckFailure from None
    return channel


def history_cog(interaction):
    cog = interaction.client.get_cog("MessageHistory")
    if cog is None:
        raise app_commands.CheckFailure("L'historique est temporairement indisponible.")
    return cog


def parse_message_id(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        number = int(value.rstrip("/").rsplit("/", 1)[-1])
    except ValueError:
        raise ValueError("Indique un identifiant ou un lien de message valide.") from None
    if not 0 < number < 2**64:
        raise ValueError("Indique un identifiant ou un lien de message valide.")
    return number


class HistoryView(ExpiringView):
    def __init__(self, interaction, store, channel_id, *, message_id=None, author_id=None, event_kind="changes"):
        super().__init__(timeout=120, owner_id=interaction.user.id)
        self.store = store
        self.guild_id, self.channel_id = interaction.guild_id, channel_id
        self.message_id, self.author_id, self.event_kind = message_id, author_id, event_kind
        self.initial_event_kind = event_kind
        self.bot_user = interaction.client.user
        self.page = 0
        self.entry_id = None
        self.size = 1 if message_id else 5
        self.export.disabled = message_id is None
        self.back.disabled = message_id is None

    async def interaction_check(self, interaction):
        if not await super().interaction_check(interaction):
            return False
        try:
            await source_channel(interaction, self.channel_id)
        except app_commands.CheckFailure:
            await interaction.response.send_message("❌ Tu n'as plus accès à cet historique.", ephemeral=True)
            if self.message:
                await self.message.edit(content="Accès à l'historique retiré.", embed=None, view=None, attachments=[])
            self.stop()
            return False
        return True

    async def render(self):
        rows = await self.store.records(
            self.guild_id, self.channel_id, message_id=self.message_id, author_id=self.author_id,
            event_kind=self.event_kind, offset=self.page * self.size, limit=self.size + 1,
        )
        self.previous.disabled = self.page == 0
        self.next.disabled = len(rows) <= self.size
        rows = rows[:self.size]
        embed = discord.Embed(title="📋 Suivi des messages", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
        embed.set_footer(text=str(self.bot_user), icon_url=self.bot_user.display_avatar.url)
        embed.description = f"Salon : <#{self.channel_id}> · Page {self.page + 1}"
        self.entry_id = rows[0].id if self.message_id and rows else None
        self.export.disabled = not rows or self.message_id is None or rows[0].unreadable
        self.choose.disabled = not rows or self.message_id is not None
        self.back.disabled = self.message_id is None
        if rows and self.message_id is None:
            unique = {entry.message_id: entry for entry in rows}
            self.choose.options = [discord.SelectOption(
                label=f"Message {entry.message_id}", value=str(entry.message_id),
                description=f"{EVENT_LABELS[entry.event_kind]} · {entry.snapshot.author_name or 'Auteur inconnu'}"[:100],
            ) for entry in unique.values()]
        if not rows:
            embed.description += "\nAucune version conservée pour ces critères. Les limites de conservation s'appliquent."
            return embed
        if self.message_id:
            entry = rows[0]
            embed.title = f"📋 Historique du message {entry.message_id}"
            embed.add_field(name="Événement", value=EVENT_LABELS[entry.event_kind])
            embed.add_field(name="Enregistré le", value=f"<t:{entry.recorded_at}:F>")
            embed.add_field(name="Suppression automatique au plus tard", value=f"<t:{entry.expires_at}:F>")
            embed.add_field(name="Auteur du message", value=entry.snapshot.author_text(), inline=False)
            text = "Version chiffrée illisible." if entry.unreadable else entry.snapshot.content_text()
            escaped = discord.utils.escape_markdown(text)
            embed.add_field(name="Contenu", value=escaped[:950] + ("\n… Bouton « Contenu intégral »." if len(escaped) > 950 else ""), inline=False)
            if entry.snapshot.attachments:
                embed.add_field(name="Pièces jointes", value=discord.utils.escape_markdown(entry.snapshot.attachment_text())[:950], inline=False)
        else:
            for entry in rows:
                preview = "Version chiffrée illisible." if entry.unreadable else discord.utils.escape_markdown(entry.snapshot.content_text())[:230]
                embed.add_field(
                    name=EVENT_LABELS[entry.event_kind],
                    value=f"<t:{entry.recorded_at}:f> · {f'<@{entry.author_id}>' if entry.author_id else 'Auteur inconnu'}\nMessage : `{entry.message_id}`\n{preview}",
                    inline=False,
                )
            embed.description += "\nUtilise `/messagehistory view` avec l'identifiant pour consulter les versions."
        return embed

    async def show(self, interaction):
        await interaction.response.defer()
        await interaction.edit_original_response(embed=await self.render(), view=self, attachments=[])

    @discord.ui.button(label="◀ Précédent", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, _button):
        self.page = max(0, self.page - 1)
        await self.show(interaction)

    @discord.ui.button(label="Suivant ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, _button):
        self.page += 1
        await self.show(interaction)

    @discord.ui.button(label="Contenu intégral", style=discord.ButtonStyle.primary)
    async def export(self, interaction, _button):
        await interaction.response.defer(ephemeral=True)
        if self.entry_id is None:
            await interaction.followup.send("Aucune version disponible à exporter.", ephemeral=True)
            return
        rows = await self.store.records(self.guild_id, self.channel_id, record_id=self.entry_id, limit=1)
        if not rows or rows[0].unreadable:
            await interaction.followup.send("Cette version a expiré, a été effacée ou est indisponible.", ephemeral=True)
            return
        entry = rows[0]
        file = text_file(
            f"Message : {entry.message_id}\nSalon : {entry.channel_id}\n"
            f"Événement : {EVENT_LABELS[entry.event_kind]}\n{entry.snapshot.transcript()}",
            f"message-{entry.message_id}-version-{entry.id}.txt",
        )
        try:
            await interaction.followup.send(file=file, ephemeral=True, allowed_mentions=NO_MENTIONS)
        finally:
            file.close()
            file.fp.close()

    @discord.ui.button(label="Retour aux événements", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, _button):
        self.message_id, self.event_kind = None, self.initial_event_kind
        self.page, self.size = 0, 5
        await self.show(interaction)

    @discord.ui.select(
        placeholder="Consulter les versions d'un message", row=1,
        options=[discord.SelectOption(label="Aucun message", value="none")], disabled=True,
    )
    async def choose(self, interaction, select):
        self.message_id = parse_message_id(select.values[0])
        self.event_kind, self.page, self.size = None, 0, 1
        await self.show(interaction)


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
class MessageHistoryCommands(app_commands.Group):
    def __init__(self):
        super().__init__(name="messagehistory", description="Consulter le suivi privé des messages et gérer sa conservation.")

    async def interaction_check(self, interaction):
        if not is_moderator(interaction):
            raise app_commands.CheckFailure
        return True

    async def open_view(self, interaction, channel, **filters):
        await interaction.response.defer(ephemeral=True)
        channel = await source_channel(interaction, channel.id if channel else interaction.channel_id)
        view = HistoryView(interaction, history_cog(interaction).store, channel.id, **filters)
        view.message = await interaction.followup.send(
            embed=await view.render(), view=view, ephemeral=True, wait=True, allowed_mentions=NO_MENTIONS,
        )

    @app_commands.command(name="recent", description="Voir les modifications et suppressions récentes d'un salon.")
    @app_commands.describe(channel="Salon d'origine ; salon actuel par défaut", user="Filtrer par auteur du message", event="Type d'événement")
    @app_commands.choices(event=[
        app_commands.Choice(name="Modifications et suppressions", value="changes"),
        app_commands.Choice(name="Modifications", value="edited"),
        app_commands.Choice(name="Suppressions", value="deleted"),
        app_commands.Choice(name="Toutes les versions", value="all"),
    ])
    async def recent(self, interaction: discord.Interaction, channel: SourceChannel | None = None,
                     user: discord.User | None = None, event: EventFilter = "changes"):
        await self.open_view(interaction, channel, author_id=user.id if user else None, event_kind=None if event == "all" else event)

    @app_commands.command(name="view", description="Consulter les versions conservées d'un message, même supprimé.")
    @app_commands.describe(message_id="Identifiant ou lien du message", channel="Salon d'origine ; salon actuel par défaut")
    async def view(self, interaction: discord.Interaction, message_id: str, channel: SourceChannel | None = None):
        try:
            parsed = parse_message_id(message_id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await self.open_view(interaction, channel, message_id=parsed, event_kind=None)

    @app_commands.command(name="status", description="Voir la durée de conservation et les limites de l'historique.")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        policy = await history_cog(interaction).store.policy(interaction.guild_id)
        embed = discord.Embed(title="🔒 Conservation des messages", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
        embed.add_field(name="État", value="Activé" if policy.enabled and policy.configured else "Désactivé (ou /setlogs non configuré)", inline=False)
        embed.add_field(name="Conservation maximale", value=f"{policy.retention_days} jour(s)")
        embed.add_field(name="Versions stockées", value=f"{policy.entry_count} / {policy.max_entries}")
        embed.add_field(name="Par message", value="10 versions maximum")
        embed.add_field(name="Protection", value="Contenu chiffré · Consultation privée · Droits du salon vérifiés", inline=False)
        embed.description = "Nettoyage toutes les 15 minutes et suppression des plus anciennes versions si une limite est atteinte. Les logs déjà envoyés sur Discord restent gérés par les administrateurs."
        embed.set_footer(text=str(interaction.client.user), icon_url=interaction.client.user.display_avatar.url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="configure", description="Régler la conservation des messages (administration seulement).")
    @app_commands.check(lambda interaction: is_admin(interaction.user))
    @app_commands.describe(
        enabled="Activer ; désactiver efface l'historique stocké (confirmation requise)",
        retention_days="Conserver de 1 à 30 jours maximum", max_entries="Plafond de 100 à 20 000 versions sur ce serveur",
        confirm="Confirmer l'effacement lors de la désactivation",
    )
    async def configure(self, interaction: discord.Interaction, enabled: bool | None = None,
                        retention_days: app_commands.Range[int, 1, 30] | None = None,
                        max_entries: app_commands.Range[int, 100, 20000] | None = None, confirm: bool = False):
        if enabled is False and not confirm:
            await interaction.response.send_message("Désactiver efface toutes les versions stockées sur ce serveur. Relance avec `confirm:true` pour confirmer. Les logs Discord et sauvegardes suivent leur propre conservation.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await history_cog(interaction).store.configure(interaction.guild_id, enabled=enabled, retention_days=retention_days, max_entries=max_entries)
        await record_admin_action(interaction.guild_id, interaction.user.id, "messagehistory.configure", f"enabled={enabled}, retention_days={retention_days}, max_entries={max_entries}")
        await interaction.followup.send("Conservation mise à jour et nettoyage appliqué." if enabled is not False else "Historique désactivé et versions stockées effacées.", ephemeral=True)

    @app_commands.command(name="purge", description="Effacer les versions stockées d'un salon ou d'un message (administration).")
    @app_commands.check(lambda interaction: is_admin(interaction.user))
    @app_commands.describe(channel="Salon d'origine", message_id="Limiter à cet identifiant ou lien de message", confirm="Confirmer l'effacement des versions stockées")
    async def purge(self, interaction: discord.Interaction, channel: SourceChannel, confirm: bool = False, message_id: str | None = None):
        if not confirm:
            await interaction.response.send_message("Relance avec `confirm:true` pour effacer les versions stockées. Les messages d'origine, logs Discord et sauvegardes ne sont pas effacés.", ephemeral=True)
            return
        try:
            parsed = parse_message_id(message_id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await source_channel(interaction, channel.id)
        count = await history_cog(interaction).store.purge(interaction.guild_id, channel.id, message_id=parsed)
        await record_admin_action(interaction.guild_id, interaction.user.id, "messagehistory.purge", f"channel_id={channel.id}, message_id={parsed}, versions={count}")
        await interaction.followup.send(f"{count} version(s) effacée(s) de l'historique stocké.", ephemeral=True)

    @app_commands.command(name="import", description="Importer un historique récent et limité d'un salon (administration).")
    @app_commands.check(lambda interaction: is_admin(interaction.user))
    @app_commands.checks.cooldown(1, 60, key=lambda interaction: interaction.guild_id)
    @app_commands.describe(channel="Salon à importer ; salon actuel par défaut", limit="Nombre maximum de messages à parcourir (200 par défaut, 1 000 maximum)")
    async def import_messages(self, interaction: discord.Interaction, channel: SourceChannel | None = None,
                              limit: app_commands.Range[int, 1, 1000] = 200):
        await interaction.response.defer(ephemeral=True)
        channel = await source_channel(interaction, channel.id if channel else interaction.channel_id)
        cog = history_cog(interaction)
        policy = await cog.store.policy(interaction.guild_id)
        if not policy.enabled or not policy.configured:
            await interaction.followup.send("Active l'historique et configure `/setlogs` avant d'importer.", ephemeral=True)
            return
        if interaction.guild_id in cog.importing_guilds:
            await interaction.followup.send("Un import est déjà en cours sur ce serveur.", ephemeral=True)
            return
        cog.importing_guilds.add(interaction.guild_id)
        scanned = imported = 0
        interrupted = False
        cutoff = discord.utils.utcnow().timestamp() - policy.retention_days * 86400
        try:
            async with asyncio.timeout(120):
                async for message in channel.history(limit=limit, after=datetime.fromtimestamp(cutoff, timezone.utc), oldest_first=False):
                    if scanned % 25 == 0:
                        await source_channel(interaction, channel.id)
                        if not is_admin(interaction.user) or (await cog.store.policy(interaction.guild_id)).generation != policy.generation:
                            interrupted = True
                            break
                    scanned += 1
                    if message.author.id == interaction.client.user.id:
                        continue
                    result = await cog.store.record(
                        interaction.guild_id, channel.id, message.id, "imported", MessageSnapshot.from_message(message),
                        source_created_at=int(message.created_at.timestamp()), expected_generation=policy.generation,
                    )
                    imported += int(result.recorded)
        except (TimeoutError, discord.HTTPException, app_commands.CheckFailure):
            interrupted = True
        finally:
            cog.importing_guilds.discard(interaction.guild_id)
        await record_admin_action(interaction.guild_id, interaction.user.id, "messagehistory.import", f"channel_id={channel.id}, scanned={scanned}, imported={imported}")
        await interaction.followup.send(
            f"{'Import interrompu' if interrupted else 'Import terminé'} : {scanned} message(s) parcouru(s), {imported} ajouté(s). "
            "Les limites de conservation restent appliquées. Seules les versions actuelles encore présentes sur Discord sont récupérées.",
            ephemeral=True,
        )


async def register(bot):
    bot.tree.add_command(MessageHistoryCommands())
