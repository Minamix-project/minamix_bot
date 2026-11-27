"""Generic confirmation for destructive actions (with a summary)."""

from collections.abc import Awaitable, Callable

import discord
from discord import Embed, Interaction
from discord.ui import Button

from src.utils.embed import set_bot_footer
from src.utils.views import ExpiringView


def add_confirmation_buttons(view, on_confirm, on_cancel, *, label="Confirmer", emoji=None):
    confirm = Button(label=label, style=discord.ButtonStyle.danger, emoji=emoji)
    cancel = Button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="❌")
    confirm.callback = on_confirm
    cancel.callback = on_cancel
    view.add_item(confirm)
    view.add_item(cancel)


async def confirm_action(
    interaction: Interaction,
    *,
    title: str,
    summary_lines: list[str],
    on_confirm: Callable[[Interaction], Awaitable[None]],
    confirm_label: str = "Confirmer",
    confirm_emoji: str = "✅",
    color: discord.Color = discord.Color.orange(),
    timeout: float = 30,
    ephemeral: bool = True,
) -> None:
    embed = Embed(title=title, description="\n".join(summary_lines), color=color)
    set_bot_footer(embed, interaction)

    view = ExpiringView(timeout=timeout, owner_id=interaction.user.id)
    async def cancel_callback(inter: Interaction):
        cancel_embed = Embed(title="❌ Action annulée", color=discord.Color.red())
        set_bot_footer(cancel_embed, inter)
        await inter.response.edit_message(embed=cancel_embed, view=None)

    add_confirmation_buttons(view, on_confirm, cancel_callback, label=confirm_label, emoji=confirm_emoji)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=ephemeral)
    view.message = await interaction.original_response()
