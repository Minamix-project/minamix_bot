"""Publish grouped GitHub release announcements with persistent Discord references."""

import asyncio
from dataclasses import asdict, dataclass
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import discord

from src.utils.db import get_db_connection


REPOSITORY = "Minamix-project/minamix_bot"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
MAX_PAGES = 10
MAX_MESSAGES = 10
MESSAGE_LIMIT = 2000
NO_MENTIONS = discord.AllowedMentions.none()
VERSION_PATTERN = re.compile(r"v?(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\Z")
ANNOUNCEMENT_PATTERN = re.compile(r"\*\*Changelog (v[0-9]+\.[0-9]+\.[0-9]+) ")


class DevlogError(Exception):
    """An actionable, user-facing publication failure."""


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str):
        match = VERSION_PATTERN.fullmatch(value.strip())
        if match is None:
            raise DevlogError("Version invalide : utilise par exemple `1.8.3` ou `v1.8.3`.")
        return cls(*(int(part) for part in match.groups()))

    @property
    def tag(self):
        return f"v{self.major}.{self.minor}.{self.patch}"

    @property
    def group(self):
        return f"{self.major}.{self.minor}"


@dataclass(frozen=True)
class Release:
    tag: str
    title: str
    url: str

    @property
    def version(self):
        return Version.parse(self.tag)


@dataclass(frozen=True)
class Publication:
    pages: tuple[str, ...]
    channel_id: int
    message_ids: tuple[int, ...] = ()
    created: int = 0
    edited: int = 0


def _request_json(path):
    request = Request(f"{API_ROOT}/{path}", headers={
        "Accept": "application/vnd.github+json", "User-Agent": "MinamixBot",
    })
    with urlopen(request, timeout=8) as response:
        return json.load(response)


def release_entry(data):
    version = Version.parse(data["tag_name"])
    if data.get("draft") or data.get("prerelease"):
        raise DevlogError("Les brouillons et préversions ne sont pas publiés dans le devlog.")
    notes = (data.get("body") or "").strip()
    match = re.match(r"PR #([1-9][0-9]*)\s*[—–-]\s*(.+)", notes)
    if match:
        title = match[2]
        url = f"https://github.com/{REPOSITORY}/pull/{match[1]}"
    else:
        title = data.get("name") or version.tag
        url = f"https://github.com/{REPOSITORY}/releases/tag/{version.tag}"
    title = re.sub(r"^\[(?:PATCH|MINOR|MAJOR)\]\s*", "", title, flags=re.IGNORECASE)
    title = " ".join(title.split())
    if not title or title == version.tag:
        title = "Mise à jour du bot"
    return Release(version.tag, title[:300], url)


def _fetch_release_group(version):
    target_data = _request_json(f"releases/tags/{Version.parse(version).tag}" if version else "releases/latest")
    target = release_entry(target_data)
    releases = {target.tag: target}
    for page in range(1, MAX_PAGES + 1):
        data = _request_json(f"releases?per_page=100&page={page}")
        found_base = False
        for item in data:
            try:
                entry = release_entry(item)
            except DevlogError:
                continue
            if entry.version.group == target.version.group and entry.version <= target.version:
                releases[entry.tag] = entry
                found_base |= entry.version.patch == 0
        if found_base or len(data) < 100:
            return tuple(sorted(releases.values(), key=lambda entry: entry.version))
    raise DevlogError("Cette série est trop ancienne ou trop longue pour être chargée intégralement (1 000 releases maximum).")


async def fetch_release_group(version=None):
    if version is not None:
        version = Version.parse(version).tag
    try:
        return await asyncio.to_thread(_fetch_release_group, version)
    except HTTPError as exc:
        if exc.code == 404:
            raise DevlogError("Aucune release publiée ne correspond à cette version.") from exc
        if exc.code in {403, 429}:
            raise DevlogError("GitHub limite temporairement les requêtes. Réessaie plus tard.") from exc
        raise DevlogError("Impossible de charger les releases GitHub. Réessaie plus tard.") from exc
    except (URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        raise DevlogError("Impossible de charger les releases GitHub. Réessaie plus tard.") from exc


def validate_channel(channel, guild, member):
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id:
        raise DevlogError("Configure un salon textuel de ce serveur avec `/setdevlog`.")
    if not channel.permissions_for(member).view_channel:
        raise DevlogError("Tu dois pouvoir voir le salon du devlog.")
    permissions = channel.permissions_for(guild.me)
    if not (permissions.view_channel and permissions.send_messages and permissions.read_message_history):
        raise DevlogError("Le bot doit pouvoir voir le salon, y envoyer des messages et lire l'historique.")


def devlog_emojis(bot, channel):
    permissions = channel.permissions_for(channel.guild.me)

    def resolve(name, fallback):
        for emoji in (*channel.guild.emojis, *bot.emojis):
            if emoji.name == name and emoji.is_usable():
                if emoji.guild_id == channel.guild.id or permissions.external_emojis:
                    return str(emoji)
        return fallback

    return resolve("kchoc", "🚀"), resolve("kgun", "🎯")


def _length(value):
    # Count UTF-16 units conservatively for Discord, including custom emoji markup.
    return len(value.encode("utf-16-le")) // 2


def _escape_inline(value):
    # Escape every delimiter; an existing Markdown link must not consume others.
    return re.sub(r"([\\`*_~|\[\]()<>])", r"\\\1", " ".join(value.split()))


def render_pages(releases, bot_name, *, major_emoji, minor_emoji):
    pages = []
    current = ""
    name = _escape_inline(bot_name)
    for release in sorted(releases, key=lambda entry: entry.version):
        version = release.version
        prefix = "-" if version.patch else major_emoji if version.minor == 0 else minor_emoji
        title = _escape_inline(release.title)
        line = f"{prefix} **Changelog {version.tag} @{name}** - [{title}]({release.url})"
        if _length(line) > MESSAGE_LIMIT:
            raise DevlogError("Une entrée du devlog dépasse la limite Discord de 2 000 caractères.")
        combined = f"{current}\n{line}" if current else line
        if _length(combined) > MESSAGE_LIMIT:
            pages.append(current)
            current = line
        else:
            current = combined
    if current:
        pages.append(current)
    if not pages or len(pages) > MAX_MESSAGES:
        raise DevlogError("Ce devlog est trop long : 10 messages de 2 000 caractères maximum par série.")
    return tuple(pages)


async def configure_devlog(guild_id, channel_id):
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO guild_config (guild_id, config_key, value) VALUES (%s, 'devlog_channel', %s) "
                "ON DUPLICATE KEY UPDATE value = %s", (guild_id, str(channel_id), str(channel_id)),
            )
    finally:
        db.close()


async def _existing_messages(channel, bot_id, group, message_ids, newest):
    messages = {}
    for message_id in message_ids:
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            continue
        if message.author.id != bot_id:
            raise DevlogError("Un message mémorisé n'appartient plus au bot ; publication interrompue.")
        messages[message.id] = message
    # Recover a send accepted by Discord just before a crash or database failure.
    async for message in channel.history(limit=100):
        if message.author.id != bot_id:
            continue
        matches = ANNOUNCEMENT_PATTERN.findall(message.content)
        if matches and all(Version.parse(tag).group == group for tag in matches):
            if any(Version.parse(tag) > newest for tag in matches):
                raise DevlogError("Un devlog plus récent existe déjà. Publie sa version ou une version ultérieure.")
            messages[message.id] = message
    if len(messages) > MAX_MESSAGES:
        raise DevlogError("Trop de messages correspondent à cette série ; vérifie le salon du devlog.")
    return sorted(messages.values(), key=lambda message: message.id)


async def publish_devlog(bot, guild, member, releases, *, preview=False):
    group = releases[-1].version.group
    db = await get_db_connection()
    try:
        await db.begin()
        async with db.cursor() as cursor:
            # Serialize publications and channel changes, including across bot processes.
            await cursor.execute(
                "SELECT value FROM guild_config WHERE guild_id = %s AND config_key = 'devlog_channel' FOR UPDATE",
                (guild.id,),
            )
            configured = await cursor.fetchone()
            if not configured:
                raise DevlogError("Configure d'abord le salon avec `/setdevlog <channel>`.")
            channel = guild.get_channel(int(configured[0]))
            validate_channel(channel, guild, member)
            await cursor.execute(
                "SELECT entries, message_ids FROM guild_devlogs "
                "WHERE guild_id = %s AND channel_id = %s AND release_group = %s",
                (guild.id, channel.id, group),
            )
            row = await cursor.fetchone()
            entries = {entry.tag: entry for entry in (Release(**item) for item in json.loads(row[0]))} if row else {}
            entries.update({entry.tag: entry for entry in releases})
            merged = sorted(entries.values(), key=lambda entry: entry.version)
            major_emoji, minor_emoji = devlog_emojis(bot, channel)
            pages = render_pages(merged, str(bot.user), major_emoji=major_emoji, minor_emoji=minor_emoji)
            if preview:
                await db.rollback()
                return Publication(pages, channel.id)
            existing = await _existing_messages(
                channel, bot.user.id, group, json.loads(row[1]) if row else [], merged[-1].version,
            )
            message_ids = []
            created = edited = 0
            for index, content in enumerate(pages):
                if index < len(existing):
                    message = existing[index]
                    if message.content != content:
                        await message.edit(content=content, allowed_mentions=NO_MENTIONS, suppress=True)
                        edited += 1
                else:
                    message = await channel.send(content, allowed_mentions=NO_MENTIONS, suppress_embeds=True)
                    created += 1
                message_ids.append(message.id)
            for message in existing[len(pages):]:
                await message.delete()
            entries_json = json.dumps([asdict(entry) for entry in merged], ensure_ascii=False)
            ids_json = json.dumps(message_ids)
            await cursor.execute(
                "INSERT INTO guild_devlogs (guild_id, channel_id, release_group, entries, message_ids) "
                "VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE "
                "entries = %s, message_ids = %s",
                (guild.id, channel.id, group, entries_json, ids_json, entries_json, ids_json),
            )
        await db.commit()
        return Publication(pages, channel.id, tuple(message_ids), created, edited)
    except BaseException:
        await db.rollback()
        raise
    finally:
        db.close()
