"""Session boundaries and common Discord components for the RP menus."""

import asyncio
from math import ceil

import discord

from src.config import GUILD_IDS
from src.utils import rp_roles as store
from src.utils.confirm import add_confirmation_buttons
from src.utils.embed import set_bot_footer
from src.utils.error_reporting import report_error
from src.utils.pagination import add_page_buttons, update_page_buttons
from src.utils.views import ExpiringView

NO_MENTIONS = discord.AllowedMentions.none()
SESSION_EXPIRED = "Cette session a expiré. Relance la commande."


def safe_text(value):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(value))


def clip_text(value, limit):
    return value.encode("utf-16-le")[:limit * 2].decode("utf-16-le", errors="ignore")


def page_window(items, page, size=25):
    total = max(1, ceil(len(items) / size))
    page = min(max(1, page), total)
    offset = (page - 1) * size
    return items[offset:offset + size], page, total


async def notify(interaction, message):
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await send(message, ephemeral=True, allowed_mentions=NO_MENTIONS)


async def ui_error(interaction, error):
    if isinstance(error, store.RoleError):
        message = str(error)
    elif isinstance(error, (discord.NotFound, discord.Forbidden)):
        message = "Ce membre ou ces données Discord ne sont plus accessibles. Actualise le menu."
    elif isinstance(error, discord.RateLimited):
        message = f"Discord limite temporairement cette action. Réessaie dans {ceil(error.retry_after)} secondes."
    else:
        reference = await report_error(
            interaction.client, guild_ids=interaction.guild_id, source="rproles.interaction",
            error=error, user=interaction.user,
        )
        message = f"Une erreur est survenue. Référence : `{reference}`"
    await notify(interaction, message)


class RoleSession:
    def __init__(self, interaction, *, management=False):
        self.guild_id = interaction.guild_id
        self.owner_id = interaction.user.id
        self.management = management
        self.active = None
        self.lock = asyncio.Lock()

    def valid_context(self, interaction):
        return (
            interaction.guild_id == self.guild_id
            and self.guild_id in GUILD_IDS
            and interaction.user.id == self.owner_id
            and isinstance(interaction.user, discord.Member)
            and interaction.user.guild.id == self.guild_id
            and interaction.guild is not None
        )

    async def authorize(self, interaction, *, admin=False, write=False):
        if not self.valid_context(interaction):
            raise store.RoleError("Cette action n'est pas disponible dans ce contexte.")
        if not self.management:
            return None
        member = await interaction.guild.fetch_member(self.owner_id) if write else interaction.user
        actor = store.Actor.from_member(member)
        if admin and not actor.admin:
            raise store.RoleError("Cette configuration est réservée à l'administration du serveur.")
        if not admin and not await store.can_manage(self.guild_id, actor):
            raise store.RoleError(store.DENIED)
        return actor

    async def show(self, interaction, view):
        previous = self.active
        view.message = await interaction.edit_original_response(
            content=None, embed=view.embed, view=view, allowed_mentions=NO_MENTIONS,
        )
        self.active = view
        if previous is not None:
            previous.stop()

    async def close(self, interaction):
        await interaction.edit_original_response(content="Menu fermé.", embed=None, view=None,
                                                allowed_mentions=NO_MENTIONS)
        self.active.stop()
        self.active = None


class RoleView(ExpiringView):
    def __init__(self, session, interaction, title, description=None, *, admin=False, timeout=300):
        super().__init__(timeout=timeout, owner_id=session.owner_id)
        self.session = session
        self.admin = admin
        self.embed = discord.Embed(title=title, description=description, color=discord.Color.purple())
        set_bot_footer(self.embed, interaction)

    async def interaction_check(self, interaction):
        if not await super().interaction_check(interaction):
            return False
        if not self.session.valid_context(interaction) or self.session.active is not self or self.is_finished():
            await notify(interaction, SESSION_EXPIRED)
            return False
        return True

    async def on_timeout(self):
        async with self.session.lock:
            if self.session.active is self:
                self.session.active = None
                await super().on_timeout()

    async def on_error(self, interaction, error, item):
        await ui_error(interaction, error)

    def action(self, callback, *, defer=True):
        async def run(interaction):
            if defer:
                await interaction.response.defer()
            async with self.session.lock:
                if self.session.active is not self or self.is_finished():
                    raise store.RoleError(SESSION_EXPIRED)
                await self.session.authorize(interaction, admin=self.admin)
                await callback(interaction)
        return run

    def button(self, label, callback, *, row=4, style=discord.ButtonStyle.secondary, defer=True):
        button = discord.ui.Button(label=label, row=row, style=style)
        button.callback = self.action(callback, defer=defer)
        self.add_item(button)
        return button

    def select(self, select, callback):
        async def pick(interaction):
            values = tuple(select.values)
            await self.action(lambda inter: callback(inter, values))(interaction)

        select.callback = pick
        self.add_item(select)

    def choices(self, options, placeholder, callback, *, row=0):
        if options:
            self.select(discord.ui.Select(placeholder=placeholder, options=options, row=row), callback)

    def pages(self, page, total, show_page, *, row=3):
        if total <= 1:
            return
        buttons = add_page_buttons(
            self, self.action(lambda inter: show_page(inter, page - 1)),
            self.action(lambda inter: show_page(inter, page + 1)), row=row,
        )
        update_page_buttons(buttons, page, total)

    def confirmation(self, confirm, cancel, *, label):
        add_confirmation_buttons(self, self.action(confirm), self.action(cancel), label=label)


class RoleModal(discord.ui.Modal):
    def __init__(self, parent, *, title):
        super().__init__(title=title, timeout=300)
        self.parent = parent

    async def interaction_check(self, interaction):
        return await self.parent.interaction_check(interaction)

    async def on_submit(self, interaction):
        await self.parent.action(self.submit)(interaction)

    async def on_error(self, interaction, error):
        await ui_error(interaction, error)


def cached_roles(guild):
    return {role.id: role for role in guild.roles}


async def fetch_roles(guild):
    return {role.id: role for role in await guild.fetch_roles()}


def role_label(role_id, roles):
    role = roles.get(role_id)
    return role.name if role else f"Rôle indisponible ({role_id})"


def sorted_roles(ids, roles):
    return sorted(ids, key=lambda role_id: (role_id not in roles, role_label(role_id, roles).casefold(), role_id))
