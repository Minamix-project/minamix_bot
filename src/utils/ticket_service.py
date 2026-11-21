"""Discord ticket lifecycle, access controls and plain-text transcript exports."""

from contextlib import asynccontextmanager
from datetime import timezone
import io
import json
import logging
import re
import unicodedata
from uuid import uuid4

import discord

from src.utils.ticket_controls import TicketCloseView, previous_ticket_controls, ticket_embed
from src.utils.ticket_logs import build_ticket_log
from src.utils.permissions import is_admin
from src.utils.tickets import MAX_CATEGORIES, TicketError, ticket_session

logger = logging.getLogger(__name__)
NO_MENTIONS = discord.AllowedMentions.none()
MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024
MAX_TRANSCRIPT_MESSAGES = 20000
DEFAULT_PANEL_TITLE = "Besoin d’aide ?"
DEFAULT_PANEL_TEXT = (
    "Choisis le type de demande ci-dessous.\n"
    "Aurum ouvrira un salon privé avec le personnel autorisé.\n"
    "Un seul ticket par catégorie d'aide peut être ouvert par membre.\n"
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
    "claimed": "Prise en charge",
    "released": "Libération",
    "deleted": "Suppression du salon",
    "deletion_requested": "Suppression demandée",
}


def is_staff(member, staff_role_ids):
    return is_admin(member) or bool(set(staff_role_ids).intersection(role.id for role in getattr(member, "roles", ())))


def admin_roles(guild):
    return [role for role in guild.roles if not role.is_default()
            and (role.permissions.administrator or role.permissions.manage_guild)]


def require_ticket_channel(interaction, ticket):
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
    return channel


def require_access(interaction, ticket, *, staff_only=False):
    require_ticket_channel(interaction, ticket)
    staff = is_staff(interaction.user, ticket.staff_role_ids)
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


def validate_staff_roles(guild, staff_roles):
    if len(staff_roles) > 10 or any(
        role is None or role.guild.id != guild.id or role.is_default() or role.managed for role in staff_roles
    ):
        raise TicketError("Choisis jusqu’à 10 rôles de support dédiés, différents de @everyone et des rôles d’intégration.")


def validate_setup(guild, channel, category, transcript_channel, logs_channel=None):
    validate_text_channel(channel, guild)
    if not isinstance(category, discord.CategoryChannel) or category.guild.id != guild.id:
        raise TicketError("Choisis une catégorie Discord de ce serveur pour les tickets.")
    permissions = category.permissions_for(guild.me)
    if not (permissions.manage_channels and permissions.manage_roles):
        raise TicketError("Le bot doit pouvoir gérer les salons et les permissions dans la catégorie des tickets.")
    if transcript_channel is not None:
        validate_text_channel(transcript_channel, guild, attachments=True)
        if transcript_channel.permissions_for(guild.default_role).view_channel:
            raise TicketError("Le salon des transcripts doit être privé pour protéger le contenu des tickets.")
    if logs_channel is not None:
        validate_text_channel(logs_channel, guild)


def member_overwrite():
    return discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
        embed_links=True,
        use_application_commands=True,
    )


def private_overwrites(guild, member, staff_roles):
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
        **{role: member_overwrite() for role in staff_roles},
        **{role: member_overwrite() for role in admin_roles(guild)},
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


def archive_overwrites(guild, overwrites, staff_role_ids, *, creator_id):
    result = {}
    for target, overwrite in overwrites.items():
        copy = discord.PermissionOverwrite.from_pair(*overwrite.pair())
        if target.id != guild.me.id:
            staff_target = (
                target.id in staff_role_ids if isinstance(target, discord.Role) else is_staff(target, staff_role_ids)
            )
            if isinstance(target, discord.Role) and target in admin_roles(guild):
                staff_target = True
            copy.view_channel = bool(staff_target)
            copy.update(
                send_messages=bool(staff_target),
                read_message_history=True if staff_target else copy.read_message_history,
                use_application_commands=True if staff_target else copy.use_application_commands,
                send_messages_in_threads=False,
                create_public_threads=False,
                create_private_threads=False,
                add_reactions=False,
            )
        result[target] = copy
    return result


def replace_staff_overwrites(guild, ticket, overwrites, staff_roles):
    """Replace managed role grants while retaining explicit participant access."""
    new_ids = {role.id for role in staff_roles}
    removed_ids = (set(ticket.staff_role_ids) | set(ticket.admin_role_ids)) - new_ids
    updated = {
        target: discord.PermissionOverwrite.from_pair(*overwrite.pair())
        for target, overwrite in overwrites.items()
        if not (isinstance(target, discord.Role) and target.id in removed_ids)
    }
    for role in staff_roles:
        updated[role] = member_overwrite()
    default = updated.setdefault(guild.default_role, discord.PermissionOverwrite())
    default.view_channel = False
    for target, overwrite in updated.items():
        if (
            isinstance(target, discord.Member)
            and target.id != guild.me.id
            and is_staff(target, new_ids)
        ):
            # A former guest's explicit removal must not block new support access.
            overwrite.update(view_channel=True, send_messages=True, read_message_history=True, use_application_commands=True)
    if ticket.status == "closed":
        updated = archive_overwrites(guild, updated, new_ids, creator_id=ticket.creator_id)
    return updated


def replace_saved_staff(guild, ticket, staff_roles):
    """Update a closed ticket's future permissions without losing unresolved members."""
    if ticket.saved_overwrites is None:
        return None
    retained = [
        entry for entry in json.loads(ticket.saved_overwrites)
        if not (entry["type"] == "role" and entry["id"] in {*ticket.staff_role_ids, *ticket.admin_role_ids})
    ]
    new_ids = {role.id for role in staff_roles}
    retained = [entry for entry in retained if not (entry["type"] == "role" and entry["id"] in new_ids)]
    for entry in retained:
        if entry["type"] != "member" or entry["id"] in {ticket.creator_id, guild.me.id}:
            continue
        member = guild.get_member(entry["id"])
        if member is not None and is_staff(member, new_ids):
            overwrite = discord.PermissionOverwrite.from_pair(
                discord.Permissions(entry["allow"]), discord.Permissions(entry["deny"]),
            )
            overwrite.view_channel = True
            allow, deny = overwrite.pair()
            entry.update(allow=allow.value, deny=deny.value)
    return json.dumps([*retained, *serialize_overwrites({role: member_overwrite() for role in staff_roles})])


def opening_embed(bot_user, ticket, category):
    embed = ticket_embed(
        bot_user, title=f"{category['emoji']} Ticket #{ticket.reference} — {category['name']}",
        description=category["welcome"] + "\n\nL'équipe de support te répondra prochainement.\n"
        "Pour fermer ce ticket, appuie sur le bouton **Fermer le ticket**.",
    )
    embed.add_field(name="Historique", value="Un transcript sera conservé à la fermeture.", inline=False)
    if ticket.status == "closed":
        embed.color = discord.Color.red()
        embed.description = "🔒 **Ce ticket est fermé.** Le personnel peut le rouvrir ou le supprimer avec les boutons ci-dessous."
        embed.add_field(name="État", value="🔒 Fermé", inline=False)
    if ticket.claimed_by is not None:
        value = f"<@{ticket.claimed_by}>"
        if ticket.claimed_at:
            value += " · " + discord.utils.format_dt(ticket.claimed_at.replace(tzinfo=timezone.utc))
        embed.add_field(name="Responsable", value=value, inline=False)
    else:
        embed.add_field(
            name="Prise en charge", value="En attente d'un membre du staff." if ticket.claim_enabled else "Désactivée.",
            inline=False,
        )
    return embed


def shorten_channel_name(value, limit):
    while len(value.encode("utf-16-le")) // 2 > limit:
        value = value[:-1]
    return value


def unclaimed_channel_name(base_name, *, claimable):
    base = base_name.removesuffix("-🔴")
    return shorten_channel_name(base, 97) + "-🔴" if claimable else base


def claimed_channel_name(base_name, guild, user_id, *, member=None, emoji="🟢"):
    member = member or guild.get_member(user_id)
    label = member.display_name if member else str(user_id)
    label = re.sub(r"[^\w-]+", "-", label.casefold()).strip("-_") or str(user_id)
    emoji_length = len(emoji.encode("utf-16-le")) // 2
    base = shorten_channel_name(base_name.removesuffix("-🔴"), min(80, 100 - emoji_length - 14))
    return shorten_channel_name(f"{base}-{emoji}-{label}", 100)


def ticket_channel_name(ticket, guild, base, *, member=None):
    if ticket.claimed_by is not None:
        # Reserve room for the closure marker without dropping the member's name.
        name = claimed_channel_name(base, guild, ticket.claimed_by, member=member, emoji=ticket.claim_emoji)
    else:
        name = unclaimed_channel_name(base, claimable=ticket.status == "open" and ticket.claim_enabled)
    return shorten_channel_name(name, 97) + "-🔒" if ticket.status == "closed" else name


def ticket_base_name(ticket, channel):
    if ticket.channel_base_name is not None:
        return ticket.channel_base_name
    if ticket.claim_base_name is not None:
        return ticket.claim_base_name.removesuffix("-🔴")
    if channel.name in {f"ticket-{ticket.id}", f"ticket-{ticket.ticket_number}"}:
        return f"ticket-{ticket.reference}"
    return channel.name.removesuffix("-🔒").removesuffix("-🔴")


def validate_staff_emoji(value):
    value = value.strip()
    keycap = "\u20e3" in value
    def allowed(char):
        return (unicodedata.category(char) in {"So", "Sk"}
                or char in {"\u200d", "\ufe0e", "\ufe0f", "\u20e3", "‼", "⁉", "ℹ"}
                or 0xE0020 <= ord(char) <= 0xE007F or (keycap and char in "0123456789#*"))
    bases = [char for char in value if unicodedata.category(char) == "So"]
    flag = len(bases) == 2 and all(0x1F1E6 <= ord(char) <= 0x1F1FF for char in bases)
    if (not value or len(value.encode("utf-16-le")) // 2 > 32 or not all(allowed(char) for char in value)
            or not (bases or keycap or any(char in value for char in "‼⁉ℹ"))
            or (keycap and sum(char in "0123456789#*" for char in value) != 1)
            or (len(bases) > 1 and "\u200d" not in value and not flag)):
        raise TicketError("Choisis un seul emoji Unicode, par exemple 🎯. Les emojis personnalisés Discord ne sont pas utilisables dans un nom de salon.")
    return value


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
        f"Catégorie : {ticket.label}",
        f"Création : {utc_label(ticket.created_at)}",
        f"État : {'Fermé' if ticket.status == 'closed' else 'Ouvert'}",
        f"Responsable : {ticket.claimed_by or '—'}",
        f"Prise en charge : {utc_label(ticket.claimed_at)}",
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
    async def panels(self, interaction):
        if not is_admin(interaction.user):
            raise TicketError("Cette action est réservée à l'administration du serveur.")
        async with ticket_session(interaction.guild_id) as session:
            return await session.panels()

    async def categories(self, interaction):
        async with ticket_session(interaction.guild_id) as session:
            return await session.categories()

    async def welcome_message(self, guild, channel, ticket):
        if ticket.welcome_message_id:
            try:
                message = await channel.fetch_message(ticket.welcome_message_id)
                if message.author.id == guild.me.id:
                    return message
            except discord.NotFound:
                pass
        async for message in channel.history(limit=50, oldest_first=True):
            if message.author.id == guild.me.id and any(
                f"Ticket #{ticket.reference}" in (embed.title or "")
                or f"Ticket #{ticket.id} —" in (embed.title or "") for embed in message.embeds
            ):
                return message
        return None

    async def sync_category_tickets(self, guild, category, session, undo):
        staff_roles = [guild.get_role(role_id) for role_id in category["staff_role_ids"]]
        validate_staff_roles(guild, staff_roles)
        administrators = admin_roles(guild)
        management_roles = list({role.id: role for role in [*staff_roles, *administrators]}.values())
        plans = []
        for ticket in await session.for_category(category["category_key"]):
            if ticket.status == "deleted":
                continue
            if (ticket.category_version == category["version"]
                    and set(ticket.staff_role_ids) == set(category["staff_role_ids"])
                    and set(ticket.admin_role_ids) == {role.id for role in administrators}):
                continue
            channel = guild.get_channel(ticket.channel_id)
            if channel is None:
                try:
                    channel = await guild.fetch_channel(ticket.channel_id)
                except discord.NotFound:
                    continue
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id:
                raise TicketError(f"Le salon du ticket #{ticket.reference} n'est pas un salon textuel de ce serveur.")
            permissions = channel.permissions_for(guild.me)
            if not (permissions.manage_channels and permissions.manage_roles):
                raise TicketError(f"Le bot doit pouvoir gérer le salon et les permissions du ticket #{ticket.reference}.")
            message = await self.welcome_message(guild, channel, ticket)
            old = channel.overwrites
            plans.append((ticket, channel, old, replace_staff_overwrites(guild, ticket, old, management_roles),
                          replace_saved_staff(guild, ticket, management_roles), message))
        for ticket, channel, old, updated, saved, message in plans:
            old_topic = channel.topic
            await channel.edit(overwrites=updated, topic=f"Aurum | {category['name']} | {ticket.creator_id}",
                               reason="Mise à jour de la catégorie de support")
            undo.append(lambda channel=channel, old=old, topic=old_topic: channel.edit(overwrites=old, topic=topic))
            if message:
                old_embeds = list(message.embeds)
                old_view = previous_ticket_controls(self, message)
                await message.edit(embed=opening_embed(guild.me, ticket, category),
                                   view=TicketCloseView(self, ticket), allowed_mentions=NO_MENTIONS)
                undo.append(lambda message=message, embeds=old_embeds, view=old_view:
                            message.edit(embeds=embeds, view=view, allowed_mentions=NO_MENTIONS))
            await self.sync_ticket_name(guild, channel, ticket, session, undo)
            await session.update_category(ticket, category, saved, message.id if message else ticket.welcome_message_id,
                                          admin_role_ids=tuple(role.id for role in administrators))

    async def refresh_opening(self, guild, channel, ticket, session, undo, *, create=False):
        message = await self.welcome_message(guild, channel, ticket)
        if message is None and not create:
            return
        category = await session.category(ticket.category, include_inactive=True)
        if category is None:
            category = {"name": ticket.label, "emoji": "🎫", "welcome": "Explique ta demande au staff."}
        embed = opening_embed(guild.me, ticket, category)
        view = TicketCloseView(self, ticket)
        if message:
            old_embeds, old_view = list(message.embeds), previous_ticket_controls(self, message)
            await message.edit(embed=embed, view=view, allowed_mentions=NO_MENTIONS)
            undo.append(lambda: message.edit(embeds=old_embeds, view=old_view, allowed_mentions=NO_MENTIONS))
        else:
            message = await channel.send(embed=embed, view=view, allowed_mentions=NO_MENTIONS)
            undo.append(message.delete)
        if message.id != ticket.welcome_message_id:
            await session.set_welcome_message(ticket, message.id)

    async def assign(self, interaction, *, release=False):
        async with operation(interaction.guild_id) as (session, undo):
            ticket = await session.get(interaction.channel_id)
            channel = require_ticket_channel(interaction, ticket)
            if release:
                if ticket.claimed_by is None:
                    raise TicketError("Ce ticket n'est pas pris en charge.")
                if ticket.claimed_by != interaction.user.id and not is_admin(interaction.user):
                    raise TicketError("Seul le responsable actuel ou un administrateur (Gérer le serveur) peut libérer ce ticket.")
                base = ticket_base_name(ticket, channel)
                await session.release(ticket)
            else:
                if ticket.status != "open":
                    raise TicketError("Ce ticket est fermé. Rouvre-le avant de le prendre en charge.")
                if not ticket.claim_enabled:
                    raise TicketError("La prise en charge est désactivée pour cette catégorie.")
                category = await session.category(ticket.category, include_inactive=True)
                roles = category["staff_role_ids"] if category else ticket.staff_role_ids
                if not is_staff(interaction.user, roles):
                    raise TicketError("Tu dois avoir un rôle de support de cette catégorie ou Gérer le serveur pour prendre en charge ce ticket.")
                if ticket.claimed_by is not None:
                    raise TicketError(f"Ce ticket est déjà pris en charge par <@{ticket.claimed_by}>. Son responsable ou un administrateur peut le libérer.")
                base = ticket_base_name(ticket, channel)
                await session.claim(ticket, interaction.user.id, base)
            previous_owner = ticket.claimed_by
            ticket = await session.get(channel.id)
            name = ticket_channel_name(ticket, interaction.guild, base, member=interaction.user if not release else None)
            if ticket.channel_base_name is None:
                await session.set_channel_base_name(ticket, base)
            old_name = channel.name
            await channel.edit(name=name, reason="Libération du ticket" if release else "Prise en charge du ticket")
            undo.append(lambda: channel.edit(name=old_name))
            ticket = await session.get(channel.id)
            action = "released" if release else "claimed"
            if release:
                await session.event(ticket, interaction.user.id, action, str(previous_owner), staff=True)
            else:
                await session.event(ticket, interaction.user.id, action, staff=True)
            await self.refresh_opening(interaction.guild, channel, ticket, session, undo, create=True)
        await self.log_action(interaction.guild, ticket, action, interaction.user.id,
                              detail=str(previous_owner) if release else None)
        return ticket

    async def save_category(self, interaction, draft, view_factory):
        if not is_admin(interaction.user):
            raise TicketError("Cette action est réservée à l'administration du serveur.")
        draft.name, draft.emoji = draft.name.strip(), draft.emoji.strip()
        draft.description, draft.welcome = draft.description.strip(), draft.welcome.strip()
        if not (1 <= len(draft.name) <= 100 and 1 <= len(draft.description) <= 100
                and 1 <= len(draft.welcome) <= 2000 and 1 <= len(draft.emoji) <= 100):
            raise TicketError("Indique un nom et une description de 100 caractères maximum, un emoji et un message de 2 000 caractères maximum.")
        emoji = discord.PartialEmoji.from_str(draft.emoji)
        if emoji.is_custom_emoji():
            resolved = interaction.client.get_emoji(emoji.id)
            if resolved is None or not resolved.is_usable():
                raise TicketError("Cet emoji personnalisé n'est pas accessible au bot.")
        elif not any(unicodedata.category(char) in {"So", "Sk"} or char == "\u20e3" for char in draft.emoji):
            raise TicketError("Indique un emoji Unicode ou un emoji personnalisé accessible au bot.")
        validate_staff_roles(interaction.guild, [interaction.guild.get_role(role_id) for role_id in draft.staff_role_ids])
        async with operation(interaction.guild_id) as (session, undo):
            old_categories = await session.categories()
            creating = draft.version == 0 and not draft.category_key
            if creating:
                if len(old_categories) >= MAX_CATEGORIES:
                    raise TicketError(f"Tu peux créer au maximum {MAX_CATEGORIES} catégories actives par serveur.")
                key = uuid4().hex
                await session.create_category(key, draft)
            else:
                previous = await session.category(draft.category_key)
                if previous is None or previous["version"] != draft.version:
                    raise TicketError("Cette catégorie a été modifiée ou supprimée. Rouvre le gestionnaire avant de l'éditer.")
                key = draft.category_key
                await session.save_category(draft)
            category = await session.category(key)
            await self.sync_category_tickets(interaction.guild, category, session, undo)
            await self.update_category_menus(interaction.guild, session, view_factory, old_categories, undo)
            await session.execute(
                "INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)",
                (interaction.guild_id, interaction.user.id, f"ticket.category{'_create' if creating else ''}: key={key}"),
            )
        return category

    async def update_category_menus(self, guild, session, view_factory, previous, undo):
        categories = await session.categories()
        for panel in await session.panels():
            channel = guild.get_channel(panel["channel_id"])
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                message = await channel.fetch_message(panel["message_id"])
            except discord.NotFound:
                continue
            if message.author.id != guild.me.id:
                continue
            view, old_view = view_factory(), view_factory()
            view.set_categories(categories)
            old_view.set_categories(previous)
            await message.edit(view=view)
            undo.append(lambda message=message, old_view=old_view: message.edit(view=old_view))

    async def delete_category(self, interaction, key, version, view_factory):
        if not is_admin(interaction.user):
            raise TicketError("Cette action est réservée à l'administration du serveur.")
        async with operation(interaction.guild_id) as (session, undo):
            category = await session.category(key)
            if category is None or category["version"] != version:
                raise TicketError("Cette catégorie a été modifiée ou supprimée. Rouvre le gestionnaire avant de la supprimer.")
            previous = await session.categories()
            await session.delete_category(key)
            await self.update_category_menus(interaction.guild, session, view_factory, previous, undo)
            await session.execute(
                "INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)",
                (interaction.guild_id, interaction.user.id, f"ticket.category_delete: key={key}"),
            )

    async def sync_categories(self, guild):
        async with ticket_session(guild.id) as session:
            categories = await session.categories()
            known_keys = {category["category_key"] for category in categories}
            for ticket in await session.all():
                if ticket.category not in known_keys:
                    category = await session.category(ticket.category, include_inactive=True)
                    if category:
                        categories.append(category)
                    known_keys.add(ticket.category)
        for category in categories:
            try:
                async with operation(guild.id) as (session, undo):
                    current = await session.category(category["category_key"], include_inactive=True)
                    await self.sync_category_tickets(guild, current, session, undo)
            except (TicketError, discord.HTTPException):
                logger.warning("Could not synchronize ticket category guild=%s category=%s", guild.id, category["category_key"])

    async def panel(self, interaction, draft, view):
        if not is_admin(interaction.user):
            raise TicketError("Cette action est réservée à l'administration du serveur.")
        guild = interaction.guild
        channel = guild.get_channel(draft.channel_id)
        category = guild.get_channel(draft.category_id)
        transcript_channel = guild.get_channel(draft.transcript_channel_id) if draft.transcript_channel_id else None
        logs_channel = guild.get_channel(draft.logs_channel_id) if draft.logs_channel_id else None
        if draft.transcript_channel_id and transcript_channel is None:
            raise TicketError("Le salon des transcripts n'existe plus. Sélectionne un autre salon.")
        if draft.logs_channel_id and logs_channel is None:
            raise TicketError("Le salon des logs de tickets n'existe plus. Sélectionne un autre salon.")
        validate_setup(guild, channel, category, transcript_channel, logs_channel)
        if logs_channel and not logs_channel.permissions_for(interaction.user).view_channel:
            raise TicketError("Tu dois pouvoir voir le salon des logs de tickets.")
        if not channel.permissions_for(interaction.user).view_channel:
            raise TicketError("Tu dois pouvoir voir le salon du panneau.")
        name = draft.name.strip()
        title = (draft.title or "").strip() or DEFAULT_PANEL_TITLE
        text = (draft.text or "").strip().replace("\\n", "\n") or DEFAULT_PANEL_TEXT
        if not 1 <= len(name) <= 80 or len(title) > 256 or len(text) > 4000:
            raise TicketError("Le nom est limité à 80 caractères, le titre à 256 et le texte à 4 000.")
        embed = discord.Embed(title=title, description=text, color=discord.Color.blurple())
        bot_user = interaction.client.user
        embed.set_footer(text=bot_user.name, icon_url=bot_user.display_avatar.url)
        async with operation(interaction.guild_id) as (session, undo):
            previous = await session.panel(draft.id) if draft.id else None
            if draft.id and (previous is None or previous["version"] != draft.version):
                raise TicketError("Ce panneau a été modifié ou supprimé. Rouvre le gestionnaire avant de l'éditer.")
            if await session.get(channel.id):
                raise TicketError("Le panneau doit être envoyé dans un salon qui n'est pas un ticket.")
            if view is not None:
                view.set_categories(await session.categories())
            message = None
            if previous and previous["channel_id"] == channel.id:
                try:
                    message = await channel.fetch_message(previous["message_id"])
                except discord.NotFound:
                    pass
            if message is not None:
                if message.author.id != bot_user.id:
                    raise TicketError("Le message du panneau n'appartient pas au bot.")
                old_embeds = list(message.embeds)
                await message.edit(embed=embed, view=view, allowed_mentions=NO_MENTIONS)
                undo.append(lambda: message.edit(embeds=old_embeds, view=view, allowed_mentions=NO_MENTIONS))
            else:
                message = await channel.send(embed=embed, view=view, allowed_mentions=NO_MENTIONS)
                undo.append(message.delete)
            panel_id = await session.save_panel(
                channel.id,
                message.id,
                category.id,
                draft.transcript_channel_id,
                logs_channel_id=draft.logs_channel_id,
                panel_id=draft.id,
                name=name,
                title=title,
                text=text,
            )
            await session.execute(
                "INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)",
                (guild.id, interaction.user.id, f"ticket.panel: id={panel_id} channel={channel.id}"),
            )
        # Disable only the previous message of this panel; other panels remain active.
        if previous and (previous["channel_id"], previous["message_id"]) != (channel.id, message.id):
            old_channel = guild.get_channel(previous["channel_id"])
            if old_channel:
                try:
                    old = await old_channel.fetch_message(previous["message_id"])
                    await old.edit(view=None)
                except discord.HTTPException:
                    pass
        return message

    async def delete_panel(self, interaction, panel_id, version, view):
        if not is_admin(interaction.user):
            raise TicketError("Cette action est réservée à l'administration du serveur.")
        async with operation(interaction.guild_id) as (session, undo):
            panel = await session.panel(panel_id)
            if panel is None or panel["version"] != version:
                raise TicketError("Ce panneau a été modifié ou supprimé. Actualise le gestionnaire.")
            channel = interaction.guild.get_channel(panel["channel_id"])
            if channel:
                try:
                    message = await channel.fetch_message(panel["message_id"])
                    if message.author.id != interaction.client.user.id:
                        raise TicketError("Le message du panneau n'appartient pas au bot.")
                    await message.edit(view=None)
                    undo.append(lambda: message.edit(view=view))
                except discord.NotFound:
                    pass
            await session.delete_panel(panel_id)
            await session.execute(
                "INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)",
                (interaction.guild_id, interaction.user.id, f"ticket.panel_delete: id={panel_id}"),
            )

    @staticmethod
    def visible_panels(interaction, panels):
        return [
            panel for panel in panels
            if isinstance(channel := interaction.guild.get_channel(panel["channel_id"]), discord.TextChannel)
            and channel.permissions_for(interaction.user).view_channel
        ]

    async def creation_panels(self, interaction):
        async with ticket_session(interaction.guild_id) as session:
            return self.visible_panels(interaction, await session.panels())

    async def create(self, interaction, category, *, direct=False, user=None, panel_id=None):
        if user is not None and not is_admin(interaction.user):
            raise TicketError("Seule l'administration peut créer un ticket pour un autre membre avec `user`.")
        creator = user if user is not None else interaction.user
        if creator.guild.id != interaction.guild_id or creator.bot:
            raise TicketError("Choisis un membre de ce serveur qui n'est pas un bot.")
        async with operation(interaction.guild_id) as (session, undo):
            option = await session.category(category)
            if option is None:
                raise TicketError("Cette catégorie de ticket est inconnue.")
            if direct:
                panels = self.visible_panels(interaction, await session.panels())
                if panel_id is not None:
                    panel = next((panel for panel in panels if panel["id"] == panel_id), None)
                    if panel is None:
                        raise TicketError("Ce panneau n'est plus disponible ou tu n'as pas accès à son salon.")
                else:
                    local = [panel for panel in panels if panel["channel_id"] == interaction.channel_id]
                    candidates = local if local else panels
                    if not candidates:
                        raise TicketError("Aucun panneau de support n'est disponible. Contacte l'administration.")
                    if len(candidates) != 1:
                        raise TicketError("Plusieurs panneaux sont disponibles. Choisis-en un avec le paramètre `panel`.")
                    panel = candidates[0]
            else:
                panel = await session.panel_for_message(interaction.channel_id, interaction.message.id)
            if panel is None:
                raise TicketError("Ce panneau n'est plus actif. Utilise un panneau de support disponible.")
            active = await session.active(creator.id, category)
            if active:
                owner = "Tu as" if creator.id == interaction.user.id else "Ce membre a"
                if interaction.guild.get_channel(active.channel_id) is not None:
                    raise TicketError(f"{owner} déjà un ticket ouvert dans cette catégorie : <#{active.channel_id}>.")
                raise TicketError(
                    "Le précédent ticket de cette catégorie a été supprimé. Le personnel doit régulariser son état "
                    "avec `/ticket reconcile` avant d'en créer un autre."
                )
            guild = interaction.guild
            destination = guild.get_channel(panel["category_id"])
            staff_roles = [guild.get_role(role_id) for role_id in option["staff_role_ids"]]
            validate_staff_roles(guild, staff_roles)
            validate_setup(guild, guild.get_channel(panel["channel_id"]), destination, None)
            if len(destination.channels) >= 50:
                raise TicketError("La catégorie de support est pleine. Contacte le personnel.")
            number = await session.next_number()
            base_name = f"ticket-{number:04d}"
            channel = await guild.create_text_channel(
                unclaimed_channel_name(base_name, claimable=bool(option["claim_enabled"])),
                category=destination,
                overwrites=private_overwrites(guild, creator, staff_roles),
                topic=f"Aurum | {option['name']} | {creator.id}",
                reason="Création d'un ticket de support",
            )
            undo.append(channel.delete)
            await session.create(channel.id, creator.id, category, panel, number=number,
                                 staff_role_ids=option["staff_role_ids"], category_version=option["version"],
                                 channel_base_name=base_name, admin_role_ids=tuple(role.id for role in admin_roles(guild)))
            ticket = await session.get(channel.id)
            await session.event(
                ticket,
                interaction.user.id,
                "created",
                option["name"],
                staff=is_staff(interaction.user, ticket.staff_role_ids),
            )
            embed = opening_embed(interaction.client.user, ticket, option)
            message = await channel.send(
                f"Bienvenue <@{creator.id}> !",
                embed=embed,
                view=TicketCloseView(self, ticket),
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False, users=[creator], replied_user=False
                ),
            )
            await session.set_welcome_message(ticket, message.id)
        await self.log_action(interaction.guild, ticket, "created", interaction.user.id)
        return ticket

    async def creator_ticket(self, interaction):
        async with ticket_session(interaction.guild_id) as session:
            ticket = await session.get(interaction.channel_id)
            require_access(interaction, ticket)
            self.require_creator(interaction, ticket)
            if ticket.status != "open":
                raise TicketError("Ce ticket est déjà fermé.")
            return ticket

    @staticmethod
    def require_creator(interaction, ticket):
        if interaction.user.id != ticket.creator_id:
            raise TicketError(
                "Seul le créateur du ticket peut utiliser ce bouton. Le personnel peut utiliser `/ticket close`."
            )

    async def mutate(
        self, interaction, action, *, user=None, name=None, reason=None, creator_only=False, expected_ticket_id=None
    ):
        async with operation(interaction.guild_id) as (session, undo):
            ticket = await session.get(interaction.channel_id)
            staff = require_access(interaction, ticket, staff_only=action != "closed")
            if expected_ticket_id is not None and ticket.id != expected_ticket_id:
                raise TicketError("Ce ticket ne correspond plus à la confirmation. Relance la commande.")
            if creator_only:
                if action != "closed":
                    raise ValueError("Creator-only mutation must close a ticket")
                self.require_creator(interaction, ticket)
                if ticket.id != expected_ticket_id:
                    raise TicketError("Ce ticket ne correspond plus à la confirmation. Relance la fermeture.")
            channel = interaction.channel
            if action == "reopened":
                if ticket.status != "closed":
                    raise TicketError("Ce ticket est déjà ouvert.")
                if await session.active(ticket.creator_id, ticket.category):
                    raise TicketError("Le créateur possède déjà un autre ticket ouvert dans cette catégorie.")
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
                        overwrites=archive_overwrites(
                            interaction.guild, old, ticket.staff_role_ids, creator_id=ticket.creator_id
                        ),
                        reason="Fermeture du ticket",
                    )
                    undo.append(lambda: channel.edit(overwrites=old))
                    await session.close(ticket, interaction.user.id, reason, serialize_overwrites(old))
                    detail = reason
                elif action in {"added", "removed"}:
                    if user.guild.id != interaction.guild_id or user.bot:
                        raise TicketError("Choisis un membre de ce serveur qui n'est pas un bot.")
                    if user.id == ticket.creator_id:
                        raise TicketError(
                            "Ce membre est le créateur du ticket ; il n'a pas besoin d'être ajouté."
                            if action == "added"
                            else "Tu ne peux pas retirer le créateur de son ticket."
                        )
                    if is_staff(user, ticket.staff_role_ids):
                        raise TicketError(
                            "Ce membre appartient au personnel autorisé. Son accès est géré par les rôles "
                            "de la catégorie, sans `/ticket add`."
                            if action == "added"
                            else "Tu ne peux pas retirer un membre du personnel autorisé avec cette commande. "
                            "Son accès est géré par les rôles de la catégorie."
                        )
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
                    await session.set_channel_base_name(ticket, name)
                    if ticket.claimed_by is not None:
                        await session.set_claim_base_name(ticket, name)
                        name = claimed_channel_name(name, interaction.guild, ticket.claimed_by, emoji=ticket.claim_emoji)
                    else:
                        name = unclaimed_channel_name(name, claimable=ticket.claim_enabled)
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
            if action in {"closed", "reopened"}:
                await self.sync_ticket_name(interaction.guild, channel, ticket, session, undo)
                await self.refresh_opening(interaction.guild, channel, ticket, session, undo)
            if action == "closed":
                content = await build_transcript(channel, ticket, session)
                await session.save_transcript(ticket, interaction.user.id, content)
        await self.log_action(interaction.guild, ticket, action, interaction.user.id, detail=detail)
        return ticket, content

    async def transcript(self, interaction):
        async with ticket_session(interaction.guild_id) as session:
            ticket = await session.get(interaction.channel_id)
            staff = require_access(interaction, ticket)
            # Staff can continue writing in a closed ticket: export its current history.
            content = await build_transcript(interaction.channel, ticket, session)
            await session.save_transcript(ticket, interaction.user.id, content)
            await session.event(ticket, interaction.user.id, "transcript", staff=staff)
        return ticket, content

    async def deletion_preview(self, interaction):
        async with ticket_session(interaction.guild_id) as session:
            ticket = await session.get(interaction.channel_id)
            require_access(interaction, ticket, staff_only=True)
            await self.validate_deletion(interaction, ticket, session)
        return ticket

    @staticmethod
    async def validate_deletion(interaction, ticket, session):
        if ticket.status not in {"open", "closed"}:
            raise TicketError("Ce ticket a déjà été supprimé.")
        if not interaction.channel.permissions_for(interaction.guild.me).manage_channels:
            raise TicketError("Le bot doit pouvoir gérer ce salon pour supprimer le ticket.")
        panels = await session.panels()
        protected = {panel["channel_id"] for panel in panels}
        protected.update(panel[key] for panel in panels for key in ("transcript_channel_id", "logs_channel_id")
                         if panel.get(key))
        protected.update(value for value in (ticket.transcript_channel_id, ticket.logs_channel_id) if value)
        if ticket.channel_id in protected:
            raise TicketError("Ce salon héberge un panneau ou reçoit des transcripts ou des logs. Déplace-les avant de supprimer ce ticket.")

    async def delete(self, interaction, expected_ticket_id):
        ticket = await self.deletion_preview(interaction)
        if ticket.id != expected_ticket_id:
            raise TicketError("Ce ticket ne correspond plus à la confirmation. Relance la suppression.")
        if ticket.status == "open":
            ticket, _content = await self.mutate(
                interaction, "closed", reason="Fermeture avant suppression du ticket par le personnel.",
                expected_ticket_id=expected_ticket_id,
            )
        # Commit an up-to-date archive before the irreversible Discord deletion.
        async with ticket_session(interaction.guild_id) as session:
            ticket = await session.get(interaction.channel_id)
            require_access(interaction, ticket, staff_only=True)
            await self.validate_deletion(interaction, ticket, session)
            if ticket.id != expected_ticket_id or ticket.status != "closed":
                raise TicketError("Le ticket a changé. Relance la suppression.")
            await session.event(ticket, interaction.user.id, "deletion_requested", staff=True)
            content = await build_transcript(interaction.channel, ticket, session)
            await session.save_transcript(ticket, interaction.user.id, content)
        warning = await self.send_transcript(interaction.guild, ticket, content)
        if warning:
            warning = "⚠️ Envoi au salon des transcripts impossible. Le transcript reste conservé dans les archives du ticket."
        async with ticket_session(interaction.guild_id) as session:
            ticket = await session.get(interaction.channel_id)
            require_access(interaction, ticket, staff_only=True)
            await self.validate_deletion(interaction, ticket, session)
            if ticket.id != expected_ticket_id or ticket.status != "closed":
                raise TicketError("Le ticket a été rouvert. Relance la suppression.")
            await session.delete(ticket)
            ticket = await session.get(interaction.channel_id)
            await session.event(ticket, interaction.user.id, "deleted", staff=True)
            try:
                await interaction.channel.delete(reason=f"Suppression du ticket confirmée par {interaction.user.id}")
            except discord.NotFound:
                pass
        await self.log_action(interaction.guild, ticket, "deleted", interaction.user.id)
        return ticket, warning

    async def refresh_panel_menus(self, guild, view_factory):
        """Refresh persisted menus while retaining the administrator's panel text."""
        async with ticket_session(guild.id) as session:
            panels = await session.panels()
            categories = await session.categories()
        for panel in panels:
            channel = guild.get_channel(panel["channel_id"])
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                message = await channel.fetch_message(panel["message_id"])
                if message.author.id == guild.me.id:
                    view = view_factory()
                    view.set_categories(categories)
                    await message.edit(view=view)
            except discord.NotFound:
                continue
            except discord.HTTPException:
                logger.warning("Could not refresh ticket panel guild=%s panel=%s", guild.id, panel["id"])

    async def sync_ticket_name(self, guild, channel, ticket, session, undo):
        base = ticket_base_name(ticket, channel)
        name = ticket_channel_name(ticket, guild, base)
        if name != channel.name:
            old = channel.name
            await channel.edit(name=name, reason="Mise à jour de l'état de prise en charge du ticket")
            undo.append(lambda: channel.edit(name=old))
        if ticket.channel_base_name is None:
            await session.set_channel_base_name(ticket, base)

    async def set_staff_emoji(self, interaction, emoji):
        emoji = validate_staff_emoji(emoji) if emoji is not None else None
        async with operation(interaction.guild_id) as (session, undo):
            categories = await session.categories()
            if not is_admin(interaction.user) and not any(
                set(category["staff_role_ids"]).intersection(role.id for role in interaction.user.roles)
                for category in categories
            ):
                raise TicketError("Cette commande est réservée au personnel de support et à l'administration.")
            await session.set_staff_emoji(interaction.user.id, emoji)
            for ticket in await session.for_claimant(interaction.user.id):
                channel = interaction.guild.get_channel(ticket.channel_id)
                if channel is not None:
                    await self.sync_ticket_name(interaction.guild, channel, ticket, session, undo)
            await session.execute(
                "INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)",
                (interaction.guild_id, interaction.user.id, "ticket.emoji: updated" if emoji else "ticket.emoji: reset"),
            )
        return emoji or "🟢"

    async def normalize_channel_names(self, guild):
        async with ticket_session(guild.id) as session:
            tickets = await session.all()
        for ticket in tickets:
            channel = guild.get_channel(ticket.channel_id)
            if channel is None:
                continue
            try:
                async with operation(guild.id) as (session, undo):
                    current = await session.get(ticket.channel_id)
                    if current:
                        await self.sync_ticket_name(guild, channel, current, session, undo)
            except (TicketError, discord.HTTPException):
                logger.warning("Could not normalize ticket channel guild=%s channel=%s", guild.id, ticket.channel_id)

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
            panels = await session.panels()
            protected_ids = {interaction.channel_id, *(panel["channel_id"] for panel in panels)}
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

    async def send_transcript(self, guild, ticket, content):
        if not ticket.transcript_channel_id:
            return None
        channel = guild.get_channel(ticket.transcript_channel_id)
        try:
            validate_text_channel(channel, guild, attachments=True)
            if channel.permissions_for(guild.default_role).view_channel:
                raise TicketError("Le salon des transcripts est devenu public.")
            embed = build_ticket_log(guild, ticket, "closed", ticket.closed_by)
            reason = discord.utils.escape_markdown(ticket.close_reason or "—")
            if len(reason) > 1024:
                reason = reason[:940] + "\n… Raison complète dans le transcript joint."
            embed.add_field(name="Raison", value=reason, inline=False)
            await channel.send(embed=embed, file=transcript_file(ticket, content), allowed_mentions=NO_MENTIONS)
        except (TicketError, discord.HTTPException):
            return "⚠️ Envoi au salon des transcripts impossible. Le transcript reste sauvegardé ; utilise `/ticket transcript`."
        return None

    async def log_action(self, guild, ticket, action, actor_id, *, detail=None):
        """Send summaries only to the ticket's optional, panel-specific destination."""
        if not ticket.logs_channel_id:
            return
        try:
            channel = guild.get_channel(ticket.logs_channel_id)
            validate_text_channel(channel, guild)
            embed = build_ticket_log(guild, ticket, action, actor_id, detail=detail)
            await channel.send(embed=embed, allowed_mentions=NO_MENTIONS)
        except Exception as exc:
            logger.warning("Could not send ticket action log guild=%s type=%s", guild.id, type(exc).__name__)
