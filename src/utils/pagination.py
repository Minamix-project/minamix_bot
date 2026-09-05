from collections.abc import Callable

import discord


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
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.previous.disabled = self.page <= 1
        self.indicator.label = f"{self.page}/{self.total_pages}"
        self.next.disabled = self.page >= self.total_pages

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

    @discord.ui.button(label="◀ Précédent", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.page -= 1
        await self._show_page(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True)
    async def indicator(self, _interaction: discord.Interaction, _button: discord.ui.Button):
        pass

    @discord.ui.button(label="Suivant ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _button: discord.ui.Button):
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
