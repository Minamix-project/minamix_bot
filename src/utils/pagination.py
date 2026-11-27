from collections.abc import Callable

import discord


def add_page_buttons(view, on_previous, on_next, *, row=None):
    previous = discord.ui.Button(label="◀ Précédent", style=discord.ButtonStyle.secondary, row=row)
    indicator = discord.ui.Button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True, row=row)
    following = discord.ui.Button(label="Suivant ▶", style=discord.ButtonStyle.secondary, row=row)
    previous.callback = on_previous
    following.callback = on_next
    for button in (previous, indicator, following):
        view.add_item(button)
    return previous, indicator, following


def update_page_buttons(buttons, page, total_pages):
    previous, indicator, following = buttons
    previous.disabled = page <= 1
    indicator.label = f"{page}/{total_pages}"
    following.disabled = page >= total_pages


class PaginationView(discord.ui.View):
    """Navigate through multiple embeds; only the command author may interact."""

    def __init__(self, owner_id: int, total_pages: int,
                 render_page: Callable[[int], discord.Embed],
                 initial_page: int = 1, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.total_pages = max(total_pages, 1)
        self.page = min(max(initial_page, 1), self.total_pages)
        self.render_page = render_page
        self.message: discord.Message | None = None
        self.previous, self.indicator, self.next = add_page_buttons(self, self._previous_page, self._next_page)
        self._update_buttons()

    def _update_buttons(self) -> None:
        update_page_buttons((self.previous, self.indicator, self.next), self.page, self.total_pages)

    def current_embed(self) -> discord.Embed:
        return self.render_page(self.page)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "❌ Seule la personne ayant lancé la commande peut changer de page.",
            ephemeral=True,
        )
        return False

    async def _show_page(self, interaction: discord.Interaction) -> None:
        self._update_buttons()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    async def _previous_page(self, interaction: discord.Interaction):
        self.page -= 1
        await self._show_page(interaction)

    async def _next_page(self, interaction: discord.Interaction):
        self.page += 1
        await self._show_page(interaction)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.HTTPException, discord.NotFound):
                pass
