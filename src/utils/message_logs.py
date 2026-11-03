"""Render message audit records without silently discarding long content."""

from dataclasses import dataclass
from io import BytesIO

import discord


UNAVAILABLE = "Indisponible : message absent du cache du bot."


@dataclass(frozen=True)
class MessageSnapshot:
    author_id: int | None = None
    author_name: str | None = None
    content: str | None = None
    attachments: tuple[tuple[int, str, str], ...] | None = None

    @classmethod
    def from_message(cls, message: discord.Message):
        return cls(
            message.author.id, str(message.author), message.content,
            tuple((item.id, item.filename, item.url) for item in message.attachments),
        )

    @classmethod
    def from_update(cls, data: dict, before: "MessageSnapshot"):
        author = data.get("author", {})
        attachments = before.attachments
        if "attachments" in data:
            attachments = tuple(
                (int(item["id"]), item["filename"], item["url"])
                for item in data["attachments"]
            )
        return cls(
            int(author["id"]) if "id" in author else before.author_id,
            author.get("username", before.author_name),
            data.get("content", before.content), attachments,
        )

    def author_text(self) -> str:
        if self.author_id is None:
            return "Auteur inconnu : message absent du cache du bot."
        name = discord.utils.escape_markdown(self.author_name or "Utilisateur inconnu")
        return f"{name} · <@{self.author_id}> (`{self.author_id}`)"

    def content_text(self) -> str:
        return UNAVAILABLE if self.content is None else self.content or "(Aucun contenu textuel)"

    def attachment_text(self) -> str:
        if self.attachments is None:
            return UNAVAILABLE
        return "\n".join(f"{name} — {url}" for _, name, url in self.attachments) or "Aucune"

    def transcript(self) -> str:
        return (
            f"Auteur du message : {self.author_name or 'Inconnu'}\n"
            f"Identifiant de l'auteur : {self.author_id or 'Inconnu'}\n"
            f"Contenu :\n{self.content_text()}\n\n"
            f"Pièces jointes :\n{self.attachment_text()}\n"
        )


def text_file(text: str, filename: str) -> discord.File:
    return discord.File(BytesIO(text.encode("utf-8")), filename=filename)


def base_embed(title: str, color: discord.Color, channel_id: int,
               message_id: int | None = None) -> discord.Embed:
    embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())
    embed.add_field(name="Salon", value=f"<#{channel_id}> (`{channel_id}`)", inline=False)
    if message_id is not None:
        embed.add_field(name="Identifiant du message", value=str(message_id))
        created_at = int(discord.utils.snowflake_time(message_id).timestamp())
        embed.add_field(name="Message envoyé le", value=f"<t:{created_at}:F>")
    return embed


def build_message_log(guild_id: int, channel_id: int, message_id: int,
                      before: MessageSnapshot, after: MessageSnapshot | None = None):
    edited = after is not None
    embed = base_embed(
        "✏️ Message modifié" if edited else "🗑️ Message supprimé",
        discord.Color.orange() if edited else discord.Color.red(),
        channel_id, message_id,
    )
    embed.add_field(name="Auteur du message", value=(after or before).author_text(), inline=False)
    if edited:
        embed.description = f"[Aller au message](https://discord.com/channels/{guild_id}/{channel_id}/{message_id})"

    truncated = False

    def add_text(name: str, value: str):
        nonlocal truncated
        # Keep user-supplied Markdown from changing the structure of the record.
        escaped = discord.utils.escape_markdown(value)
        if len(escaped) > 1024:
            escaped = escaped[:940] + "\n… Voir le fichier joint pour le contenu intégral."
            truncated = True
        embed.add_field(name=name, value=escaped, inline=False)

    if edited:
        add_text("Avant", before.content_text())
        add_text("Après", after.content_text())
        if before.attachments or after.attachments or before.attachments != after.attachments:
            add_text("Pièces jointes avant", before.attachment_text())
            add_text("Pièces jointes après", after.attachment_text())
    else:
        add_text("Contenu supprimé", before.content_text())
        if before.attachments:
            add_text("Pièces jointes supprimées", before.attachment_text())

    file = None
    if truncated:
        transcript = (
            f"Serveur : {guild_id}\nSalon : {channel_id}\nMessage : {message_id}\n"
            f"Date du journal : {embed.timestamp.isoformat()}\n\n"
            f"{'Avant' if edited else 'Message supprimé'}\n{before.transcript()}"
        )
        if edited:
            transcript += f"\nAprès\n{after.transcript()}"
        file = text_file(transcript, f"message-{message_id}.txt")
    return embed, file


def build_bulk_log(guild_id: int, channel_id: int, message_ids: set[int],
                   snapshots: dict[int, MessageSnapshot]):
    embed = base_embed("🗑️ Suppression groupée de messages", discord.Color.red(), channel_id)
    embed.add_field(name="Messages supprimés", value=str(len(message_ids)))
    embed.add_field(name="Contenus en cache", value=str(len(snapshots)))
    embed.add_field(name="Messages hors cache", value=str(len(message_ids) - len(snapshots)))
    embed.description = "Le fichier joint contient les identifiants et tous les contenus disponibles."
    records = [
        f"Serveur : {guild_id}\nSalon : {channel_id}\nDate du journal : {embed.timestamp.isoformat()}\n"
    ]
    for message_id in sorted(message_ids):
        snapshot = snapshots.get(message_id, MessageSnapshot())
        created_at = discord.utils.snowflake_time(message_id).isoformat()
        records.append(f"Message : {message_id}\nEnvoyé le : {created_at}\n{snapshot.transcript()}")
    return embed, text_file("\n\n".join(records), f"messages-supprimes-{channel_id}.txt")
