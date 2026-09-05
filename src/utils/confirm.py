"""Generic confirmation for destructive actions (with a summary)."""

from collections.abc import Awaitable, Callable

import discord
from discord import Embed, Interaction
from discord.ui import Button

from src.utils.embed import set_bot_footer
from src.utils.views import ExpiringView


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

    view = ExpiringView(timeout=timeout)
    confirm_btn = Button(label=confirm_label, style=discord.ButtonStyle.danger, emoji=confirm_emoji)
    cancel_btn = Button(label="Annuler", style=discord.ButtonStyle.grey, emoji="❌")

    async def confirm_callback(inter: Interaction):
        await on_confirm(inter)

    async def cancel_callback(inter: Interaction):
        cancel_embed = Embed(title="❌ Action annulée", color=discord.Color.red())
        set_bot_footer(cancel_embed, inter)
        await inter.response.edit_message(embed=cancel_embed, view=None)

    confirm_btn.callback = confirm_callback
    cancel_btn.callback = cancel_callback
    view.add_item(confirm_btn)
    view.add_item(cancel_btn)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=ephemeral)
    view.message = await interaction.original_response()
