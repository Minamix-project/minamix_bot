import discord
import time
import logging
from discord import Message, RawReactionActionEvent
from src.config import GUILD_IDS
from src.utils.rp import get_prefix_cache

_webhook_cache: dict[int, discord.Webhook] = {}

# message_id -> user_id : tracks webhook messages sent by characters this session
_rp_messages: dict[int, tuple[int, float]] = {}
_RP_MESSAGE_TTL = 3600
logger = logging.getLogger(__name__)


async def _get_or_create_webhook(channel: discord.TextChannel) -> discord.Webhook:
    if channel.id in _webhook_cache:
        return _webhook_cache[channel.id]

    webhooks = await channel.webhooks()
    for wh in webhooks:
        if wh.name == "MinamixRP":
            _webhook_cache[channel.id] = wh
            return wh

    wh = await channel.create_webhook(name="MinamixRP")
    _webhook_cache[channel.id] = wh
    return wh


async def register(bot):
    @bot.listen("on_message")
    async def on_message_rp(message: Message):
        cutoff = time.time() - _RP_MESSAGE_TTL
        for message_id, (_owner_id, created_at) in list(_rp_messages.items()):
            if created_at < cutoff:
                _rp_messages.pop(message_id, None)
        if message.author.bot:
            return
        if message.guild is None or message.guild.id not in GUILD_IDS:
            return

        content = message.content
        if not content:
            return

        cache = await get_prefix_cache(message.guild.id)
        matched_char = None
        matched_prefix = None

        for prefix, char_data in cache.items():
            if content.startswith(prefix):
                char_id, user_id, char_name, image_url = char_data
                if message.author.id == user_id:
                    matched_char = (char_name, image_url, user_id)
                    matched_prefix = prefix
                    break

        if not matched_char:
            return

        char_name, image_url, owner_id = matched_char
        spoken_text = content[len(matched_prefix):].strip()
        if not spoken_text:
            return

        try:
            await message.delete()
        except discord.Forbidden:
            pass

        if not isinstance(message.channel, discord.TextChannel):
            return

        try:
            webhook = await _get_or_create_webhook(message.channel)
            msg = await webhook.send(
                content=spoken_text,
                username=char_name,
                avatar_url=image_url,
                wait=True,
            )
            _rp_messages[msg.id] = (owner_id, time.time())
        except Exception:
            logger.exception("RP webhook error")

    @bot.listen("on_raw_reaction_add")
    async def on_reaction_rp_delete(payload: RawReactionActionEvent):
        if str(payload.emoji) != "❌":
            return
        if payload.message_id not in _rp_messages:
            return
        if payload.user_id != _rp_messages[payload.message_id][0]:
            return

        channel = bot.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
            await message.delete()
            del _rp_messages[payload.message_id]
        except (discord.NotFound, discord.Forbidden):
            _rp_messages.pop(payload.message_id, None)
