"""Discord ticket lifecycle, access controls and plain-text transcript exports."""

from contextlib import asynccontextmanager
from datetime import timezone
import io
import json
import logging
import re

import discord

from src.utils.permissions import is_admin
from src.utils.tickets import CATEGORIES, TicketError, ticket_session

logger = logging.getLogger(__name__)
NO_MENTIONS = discord.AllowedMentions.none()
MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024
MAX_TRANSCRIPT_MESSAGES = 20000
DEFAULT_PANEL_TITLE = "Besoin d’aide ?"
DEFAULT_PANEL_TEXT = (
    "Choisis le type de demande ci-dessous.\n"
    "Aurum ouvrira un salon privé avec le personnel autorisé.\n"
    "Un seul ticket peut être ouvert par membre.\n"
    "À la fermeture, un historique sera conservé pour le support."
)
EVENT_LABELS = {
    "created": "Création",
    "closed": "Fermeture",
    "reopened": "Réouverture",
    "added": "Membre ajouté",
    "removed": "Membre retiré",
    "renamed": "Salon renommé",
    "linked": "Utilisateur concerné",
    "transcript": "Export de l'historique",
    "panel": "Configuration du panneau",
}


def is_staff(member, staff_role_id):
    return is_admin(member) or staff_role_id in {role.id for role in getattr(member, "roles", ())}


def require_access(interaction, ticket, *, staff_only=False):
    if ticket is None:
        raise TicketError("Ce salon n'est pas un ticket enregistré sur ce serveur.")
    channel = interaction.channel
    if (
        not isinstance(channel, discord.TextChannel)
        or channel.guild.id != ticket.guild_id
        or channel.id != ticket.channel_id
    ):
        raise TicketError("Cette action doit être effectuée dans le salon du ticket.")
    if not channel.permissions_for(interaction.user).view_channel:
        raise TicketError("Tu n'as pas accès à ce ticket.")
    staff = is_staff(interaction.user, ticket.staff_role_id)
    if not staff and (staff_only or interaction.user.id != ticket.creator_id):
        raise TicketError(
            "Cette action est réservée au créateur du ticket ou au personnel autorisé."
            if not staff_only
            else "Cette action est réservée au personnel autorisé."
        )
    return staff


def validate_text_channel(channel, guild, *, attachments=False):
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id:
        raise TicketError("Choisis un salon textuel de ce serveur.")
    permissions = channel.permissions_for(guild.me)
    if not (
        permissions.view_channel
        and permissions.send_messages
        and permissions.read_message_history
        and permissions.embed_links
        and (not attachments or permissions.attach_files)
    ):
        raise TicketError(
            "Le bot doit voir le salon, lire l'historique, envoyer des messages et des liens intégrés"
            + (", et joindre des fichiers." if attachments else ".")
        )


def validate_setup(guild, channel, category, staff_role, logs_channel):
    validate_text_channel(channel, guild)
    if not isinstance(category, discord.CategoryChannel) or category.guild.id != guild.id:
        raise TicketError("Choisis une catégorie Discord de ce serveur pour les tickets.")
    if staff_role.guild.id != guild.id or staff_role.is_default() or staff_role.managed:
        raise TicketError("Choisis un rôle de support dédié, différent de @everyone et des rôles d'intégration.")
    permissions = category.permissions_for(guild.me)
    if not (permissions.manage_channels and permissions.manage_roles):
        raise TicketError("Le bot doit pouvoir gérer les salons et les permissions dans la catégorie des tickets.")
    if logs_channel is not None:
        validate_text_channel(logs_channel, guild, attachments=True)
        if logs_channel.permissions_for(guild.default_role).view_channel:
            raise TicketError("Le salon de logs doit être privé pour protéger le contenu des tickets.")


def member_overwrite():
    return discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
        embed_links=True,
        use_application_commands=True,
    )


def private_overwrites(guild, member, staff_role):
    return {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
            manage_channels=True,
            manage_roles=True,
        ),
        staff_role: member_overwrite(),
        member: member_overwrite(),
    }


def serialize_overwrites(overwrites):
    return [
        {
            "id": target.id,
            "type": "role" if isinstance(target, discord.Role) else "member",
            "allow": overwrite.pair()[0].value,
            "deny": overwrite.pair()[1].value,
        }
        for target, overwrite in overwrites.items()
    ]


async def deserialize_overwrites(guild, serialized):
    result = {}
    for entry in serialized:
        target = guild.get_role(entry["id"]) if entry["type"] == "role" else guild.get_member(entry["id"])
        if target is None and entry["type"] == "member":
            try:
                target = await guild.fetch_member(entry["id"])
            except discord.NotFound:
                continue
        if target is not None:
            result[target] = discord.PermissionOverwrite.from_pair(
                discord.Permissions(entry["allow"]),
                discord.Permissions(entry["deny"]),
            )
    return result


def archive_overwrites(guild, overwrites):
    result = {}
    for target, overwrite in overwrites.items():
        copy = discord.PermissionOverwrite.from_pair(*overwrite.pair())
        if target.id != guild.me.id:
            copy.update(
                send_messages=False,
                send_messages_in_threads=False,
                create_public_threads=False,
                create_private_threads=False,
                add_reactions=False,
            )
        result[target] = copy
    return result


def transcript_file(ticket, content):
    return discord.File(io.BytesIO(content), filename=f"ticket-{ticket.reference}.txt")


def utc_label(value):
    return value.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if value else "—"


async def build_transcript(channel, ticket, session):
    """Read the entire available history, failing explicitly rather than truncating."""
    permissions = channel.permissions_for(channel.guild.me)
    if not (permissions.view_channel and permissions.read_message_history):
        raise TicketError("Le bot doit pouvoir voir le ticket et lire son historique pour le sauvegarder.")
    staff, events = await session.history(ticket)
    lines = [
        f"Ticket #{ticket.reference}",
        f"Serveur : {ticket.guild_id}",
        f"Salon : {channel.name} ({channel.id})",
        f"Créateur : {ticket.creator_id}",
        f"Catégorie : {CATEGORIES[ticket.category]}",
        f"Création : {utc_label(ticket.created_at)}",
        f"État : {'Fermé' if ticket.status == 'closed' else 'Ouvert'}",
        f"Utilisateur concerné : {ticket.subject_id or '—'}",
        f"Fermeture : {utc_label(ticket.closed_at)}",
        f"Fermé par : {ticket.closed_by or '—'}",
        f"Raison de fermeture : {ticket.close_reason or '—'}",
        "Personnel intervenu : " + (", ".join(str(row["user_id"]) for row in staff) or "—"),
        "",
        "Historique des actions :",
    ]
    lines.extend(
        f"[{utc_label(row['created_at'])}] {row['actor_id']} — "
        f"{EVENT_LABELS.get(row['action'], row['action'])} : {row['detail'] or '—'}"
        for row in events
    )
    lines.extend(["", "Messages (les messages supprimés et les anciennes versions ne sont pas inclus) :", ""])
    content = bytearray(("\n".join(lines) + "\n").encode("utf-8"))
    limit = min(MAX_TRANSCRIPT_BYTES, channel.guild.filesize_limit - 65536)
    count = 0
    async for message in channel.history(limit=MAX_TRANSCRIPT_MESSAGES + 1, oldest_first=True):
        count += 1
        if count > MAX_TRANSCRIPT_MESSAGES:
            raise TicketError("Le ticket dépasse 20 000 messages : l'export est interrompu sans fermer le ticket.")
        text = f"[{utc_label(message.created_at)}] {message.author} ({message.author.id}) [message {message.id}]"
        if message.reference and message.reference.message_id:
            text += f" [réponse à {message.reference.message_id}]"
        text += "\n" + (message.content or "") + "\n"
        for attachment in message.attachments:
            text += f"Pièce jointe : {attachment.filename} — {attachment.url}\n"
        for embed in message.embeds:
            if embed.title:
                text += f"Contenu intégré : {embed.title}\n"
            if embed.description:
                text += embed.description + "\n"
            for field in embed.fields:
                text += f"{field.name} : {field.value}\n"
            if embed.url:
                text += f"Lien : {embed.url}\n"
            if embed.image and embed.image.url:
                text += f"Image : {embed.image.url}\n"
        if message.stickers:
            text += "Autocollants : " + ", ".join(f"{item.name} — {item.url}" for item in message.stickers) + "\n"
        content.extend((text + "\n").encode("utf-8"))
        if len(content) > limit:
            raise TicketError("Le transcript dépasse la taille de fichier autorisée : le ticket reste ouvert.")
    if len(content) > limit:
        raise TicketError("L'historique des actions dépasse la taille de fichier autorisée.")
    return bytes(content)


@asynccontextmanager
async def operation(guild_id):
    """Undo completed Discord changes if persistence fails, including at commit."""
    undo = []
    try:
        async with ticket_session(guild_id) as session:
            yield session, undo
    except BaseException:
        for callback in reversed(undo):
            try:
                await callback()
            except Exception:
                logger.exception("Could not compensate ticket Discord mutation guild=%s", guild_id)
        raise


class TicketService:
    async def panel(self, interaction, channel, category, staff_role, logs_channel, view, *, title=None, text=None):
        validate_setup(interaction.guild, channel, category, staff_role, logs_channel)
        if not channel.permissions_for(interaction.user).view_channel:
            raise TicketError("Tu dois pouvoir voir le salon du panneau.")
        title = (title or "").strip() or DEFAULT_PANEL_TITLE
        text = (text or "").strip().replace("\\n", "\n") or DEFAULT_PANEL_TEXT
        if len(title) > 256 or len(text) > 4000:
            raise TicketError("Le titre est limité à 256 caractères et le texte à 4 000 caractères.")
        embed = discord.Embed(title=title, description=text, color=discord.Color.blurple())
        bot_user = interaction.client.user
        embed.set_footer(text=bot_user.name, icon_url=bot_user.display_avatar.url)
        async with operation(interaction.guild_id) as (session, undo):
            previous = await session.panel()
            message = None
            if previous and previous["channel_id"] == channel.id:
                try:
                    message = await channel.fetch_message(previous["message_id"])
                except discord.NotFound:
                    pass
            if message is not None:
                if message.author.id != interaction.client.user.id:
                    raise TicketError("Le message du panneau n'appartient pas au bot.")
                await message.edit(embed=embed, view=view, allowed_mentions=NO_MENTIONS)
            else:
                message = await channel.send(embed=embed, view=view, allowed_mentions=NO_MENTIONS)
                undo.append(message.delete)
            await session.save_panel(
                channel.id,
                message.id,
                category.id,
                staff_role.id,
                logs_channel.id if logs_channel else None,
                title=title,
                text=text,
            )
            await session.execute(
                "INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)",
                (interaction.guild_id, interaction.user.id, f"ticket.panel: channel={channel.id}"),
            )
        # Old panels are also rejected by their persisted message ID if deletion fails.
        if previous and (previous["channel_id"], previous["message_id"]) != (channel.id, message.id):
            old_channel = interaction.guild.get_channel(previous["channel_id"])
            if old_channel:
                try:
                    old = await old_channel.fetch_message(previous["message_id"])
                    await old.edit(view=None)
                except discord.HTTPException:
                    pass
        return message

    async def create(self, interaction, category):
        if category not in CATEGORIES:
            raise TicketError("Cette catégorie de ticket est inconnue.")
        async with operation(interaction.guild_id) as (session, undo):
            panel = await session.panel()
            if not panel or (panel["channel_id"], panel["message_id"]) != (
                interaction.channel_id,
                interaction.message.id,
            ):
                raise TicketError("Ce panneau n'est plus actif. Utilise le dernier panneau de support.")
            active = await session.active(interaction.user.id)
            if active:
                if interaction.guild.get_channel(active.channel_id) is not None:
                    raise TicketError(f"Tu as déjà un ticket ouvert : <#{active.channel_id}>.")
                raise TicketError(
                    "Ton précédent ticket a été supprimé. Le personnel doit régulariser son état "
                    "avec `/ticket reconcile` avant d'en créer un autre."
                )
            guild = interaction.guild
            destination = guild.get_channel(panel["category_id"])
            staff_role = guild.get_role(panel["staff_role_id"])
            if staff_role is None:
                raise TicketError("Le rôle de support a été supprimé. Demande au personnel de reconfigurer le panneau.")
            validate_setup(guild, interaction.channel, destination, staff_role, None)
            if len(destination.channels) >= 50:
                raise TicketError("La catégorie de support est pleine. Contacte le personnel.")
            number = await session.next_number()
            channel = await guild.create_text_channel(
                f"ticket-{number:04d}",
                category=destination,
                overwrites=private_overwrites(guild, interaction.user, staff_role),
                topic=f"Aurum | {CATEGORIES[category]} | {interaction.user.id}",
                reason="Création d'un ticket de support",
            )
            undo.append(channel.delete)
            await session.create(channel.id, interaction.user.id, category, panel, number=number)
            ticket = await session.get(channel.id)
            await session.event(
                ticket,
                interaction.user.id,
                "created",
                CATEGORIES[category],
                staff=is_staff(interaction.user, ticket.staff_role_id),
            )
            await channel.send(
                f"Bienvenue <@{interaction.user.id}> !\n**{CATEGORIES[category]}** — Explique ta demande ici.\n"
                "Le personnel te répondra dès que possible. Utilise `/ticket close reason:...` pour fermer le ticket.\n"
                "Un transcript sera conservé à la fermeture. Les pièces jointes sont référencées par leurs liens.",
                allowed_mentions=NO_MENTIONS,
            )
        return ticket

    async def mutate(self, interaction, action, *, user=None, name=None, reason=None):
        async with operation(interaction.guild_id) as (session, undo):
            ticket = await session.get(interaction.channel_id)
            staff = require_access(interaction, ticket, staff_only=action != "closed")
            channel = interaction.channel
            if action == "reopened":
                if ticket.status != "closed":
                    raise TicketError("Ce ticket est déjà ouvert.")
                if await session.active(ticket.creator_id):
                    raise TicketError("Le créateur possède déjà un autre ticket ouvert.")
                if not ticket.saved_overwrites:
                    raise TicketError("Les permissions d'origine de ce ticket ne sont pas disponibles.")
                overwrites = await deserialize_overwrites(interaction.guild, json.loads(ticket.saved_overwrites))
                # Always keep the channel private, even if its category has changed.
                overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(view_channel=False)
                old = channel.overwrites
                await channel.edit(overwrites=overwrites, reason="Réouverture du ticket")
                undo.append(lambda: channel.edit(overwrites=old))
                await session.reopen(ticket)
                detail = None
                content = None
            else:
                if ticket.status != "open":
                    raise TicketError("Ce ticket est fermé. Rouvre-le avant de le modifier.")
                content = None
                if action == "closed":
                    reason = (reason or "").strip()
                    if not 1 <= len(reason) <= 1000:
                        raise TicketError("Indique une raison de fermeture de 1 à 1 000 caractères.")
                    old = channel.overwrites
                    await channel.edit(
                        overwrites=archive_overwrites(interaction.guild, old), reason="Fermeture du ticket"
                    )
                    undo.append(lambda: channel.edit(overwrites=old))
                    await session.close(ticket, interaction.user.id, reason, serialize_overwrites(old))
                    detail = reason
                elif action in {"added", "removed"}:
                    if user.guild.id != interaction.guild_id or user.bot:
                        raise TicketError("Choisis un membre de ce serveur qui n'est pas un bot.")
                    if user.id == ticket.creator_id or is_staff(user, ticket.staff_role_id):
                        raise TicketError("L'accès du créateur et du personnel est géré automatiquement.")
                    old = channel.overwrites
                    updated = dict(old)
                    updated[user] = (
                        member_overwrite() if action == "added" else discord.PermissionOverwrite(view_channel=False)
                    )
                    await channel.edit(overwrites=updated, reason="Modification des membres du ticket")
                    undo.append(lambda: channel.edit(overwrites=old))
                    detail = str(user.id)
                elif action == "renamed":
                    name = re.sub(r"[^\w-]+", "-", (name or "").strip().lower()).strip("-_")
                    if not 1 <= len(name) <= 90:
                        raise TicketError(
                            "Le nom doit contenir entre 1 et 90 caractères (lettres, chiffres ou tirets)."
                        )
                    old_name = channel.name
                    await channel.edit(name=name, reason="Renommage du ticket")
                    undo.append(lambda: channel.edit(name=old_name))
                    detail = name
                elif action == "linked":
                    if user.guild.id != interaction.guild_id:
                        raise TicketError("Choisis un membre de ce serveur.")
                    await session.link(ticket, user.id)
                    detail = str(user.id)
                else:
                    raise ValueError(f"Unknown ticket action: {action}")
            ticket = await session.get(channel.id)
            await session.event(ticket, interaction.user.id, action, detail, staff=staff)
            if action == "closed":
                content = await build_transcript(channel, ticket, session)
                await session.save_transcript(ticket, interaction.user.id, content)
        return ticket, content

    async def transcript(self, interaction):
        async with ticket_session(interaction.guild_id) as session:
            ticket = await session.get(interaction.channel_id)
            staff = require_access(interaction, ticket)
            if ticket.status == "closed":
                content = await session.latest_transcript(ticket)
                if content is None:
                    raise TicketError("Aucun transcript sauvegardé n'est disponible pour ce ticket.")
            else:
                content = await build_transcript(interaction.channel, ticket, session)
                await session.save_transcript(ticket, interaction.user.id, content)
            await session.event(ticket, interaction.user.id, "transcript", staff=staff)
        return ticket, content

    async def normalize_channel_names(self, guild):
        async with ticket_session(guild.id) as session:
            tickets = await session.all()
        for ticket in tickets:
            channel = guild.get_channel(ticket.channel_id)
            if channel and channel.name in {f"ticket-{ticket.id}", f"ticket-{ticket.ticket_number}"}:
                try:
                    await channel.edit(
                        name=f"ticket-{ticket.reference}", reason="Mise au format des numéros de tickets"
                    )
                except discord.HTTPException:
                    logger.warning(
                        "Could not normalize ticket channel guild=%s channel=%s", guild.id, ticket.channel_id
                    )

    async def purge_preview(self, interaction):
        if not is_admin(interaction.user):
            raise TicketError("Cette action est réservée à l'administration du serveur.")
        async with ticket_session(interaction.guild_id) as session:
            tickets = await session.all()
            if any(ticket.channel_id == interaction.channel_id for ticket in tickets):
                raise TicketError("Lance la purge depuis un salon qui n'est pas un ticket.")
            return tuple(ticket.id for ticket in tickets)

    async def purge(self, interaction, expected_ids):
        if not is_admin(interaction.user):
            raise TicketError("Cette action est réservée à l'administration du serveur.")
        async with ticket_session(interaction.guild_id) as session:
            tickets = await session.all()
            if tuple(ticket.id for ticket in tickets) != expected_ids:
                raise TicketError(
                    "La liste des tickets a changé. Relance `/ticket purge` pour confirmer la nouvelle liste."
                )
            panel = await session.panel()
            protected_ids = {interaction.channel_id}
            if panel:
                protected_ids.add(panel["channel_id"])
            if any(ticket.channel_id in protected_ids for ticket in tickets):
                raise TicketError(
                    "Le panneau ou la commande se trouve dans un ticket. Déplace-le avant de relancer la purge."
                )
            failed = []
            for ticket in tickets:
                try:
                    # Fetch by persisted ID: never delete unrelated channels based on their names.
                    channel = await interaction.guild.fetch_channel(ticket.channel_id)
                    await channel.delete(reason="Purge des tickets confirmée par l'administration")
                except discord.NotFound:
                    continue
                except discord.HTTPException:
                    failed.append(ticket.channel_id)
            if failed:
                raise TicketError(
                    f"{len(failed)} salon(s) n'ont pas pu être supprimés. Les autres salons ont pu être supprimés. "
                    "Les enregistrements et le compteur sont conservés : vérifie les permissions puis relance la purge."
                )
            await session.purge()
            await session.execute(
                "INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)",
                (interaction.guild_id, interaction.user.id, f"ticket.purge: count={len(tickets)}"),
            )
        return len(tickets)

    async def log_close(self, guild, ticket, content):
        if not ticket.logs_channel_id:
            return None
        channel = guild.get_channel(ticket.logs_channel_id)
        try:
            validate_text_channel(channel, guild, attachments=True)
            if channel.permissions_for(guild.default_role).view_channel:
                raise TicketError("Le salon de logs est devenu public.")
            embed = discord.Embed(
                title=f"Ticket #{ticket.reference} fermé",
                color=discord.Color.orange(),
                description=f"Créateur : <@{ticket.creator_id}>\nCatégorie : {CATEGORIES[ticket.category]}\n"
                f"Fermé par : <@{ticket.closed_by}>\nRaison : {ticket.close_reason}",
            )
            await channel.send(embed=embed, file=transcript_file(ticket, content), allowed_mentions=NO_MENTIONS)
        except (TicketError, discord.HTTPException):
            return "⚠️ Envoi aux logs impossible. Le transcript reste sauvegardé ; utilise `/ticket transcript`."
        return None
