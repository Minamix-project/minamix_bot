import random
from discord import Interaction, Embed
import discord
from src.utils.shop import get_shop_items
from src.utils.format import format_amount
from src.utils.embed import set_bot_footer
from src.utils.reactions import EGGS, _mark_found
from src.utils.purchase import show_purchase_confirmation

_COLORS = [0x3498DB, 0x2ECC71, 0x9B59B6, 0xE67E22, 0xB5264C]
_HIBISCUS = 0xB5264C
PAGE_SIZE = 4


def _render_items(numbered_items) -> list[str]:
    lines = []
    standard = [(num, r, p, n) for num, r, p, n, ex in numbered_items if not ex]
    exclusifs = [(num, r, p, n) for num, r, p, n, ex in numbered_items if ex]
    for num, role_id, prix, nom in standard:
        lines.append(f"》 **#{num}** — {format_amount(prix)}💰 : <@&{role_id}>")
    if exclusifs:
        lines.append("")
        lines.append("★―――――――――| Rôles exclusifs |―――――――――★")
        lines.append("")
        for num, role_id, prix, nom in exclusifs:
            lines.append(f"》 **#{num}** — {format_amount(prix)}💰 : <@&{role_id}>")
    return lines


class ShopView(discord.ui.View):
    def __init__(self, numbered_items, color: int, bot_user: discord.ClientUser, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.numbered_items = numbered_items
        self.color = color
        self.bot_user = bot_user
        self.total_pages = max((len(numbered_items) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        self.page = 1
        self.message: discord.Message | None = None
        self._build()

    def _page_slice(self):
        start = (self.page - 1) * PAGE_SIZE
        return self.numbered_items[start:start + PAGE_SIZE]

    def render_embed(self) -> Embed:
        lines = _render_items(self._page_slice())
        description = "\n".join(lines) + "\n\n*Utilise `/buy <numéro>` ou les boutons ci-dessous pour acheter.*"
        embed = Embed(title="🛍️ Boutique", description=description, color=self.color)
        embed.set_footer(
            text=self.bot_user.name,
            icon_url=self.bot_user.avatar.url if self.bot_user.avatar else None,
        )
        return embed

    def _build(self) -> None:
        self.clear_items()
        for num, role_id, prix, nom, _exclusif in self._page_slice():
            button = discord.ui.Button(label=f"Acheter #{num}", style=discord.ButtonStyle.green, row=0)

            async def _callback(inter: Interaction, role_id=role_id, prix=prix, nom=nom):
                await show_purchase_confirmation(inter, role_id, prix, nom, edit=True)

            button.callback = _callback
            self.add_item(button)

        if self.total_pages > 1:
            prev_btn = discord.ui.Button(label="◀ Précédent", style=discord.ButtonStyle.secondary, row=1, disabled=self.page <= 1)
            indicator = discord.ui.Button(label=f"{self.page}/{self.total_pages}", style=discord.ButtonStyle.secondary, row=1, disabled=True)
            next_btn = discord.ui.Button(label="Suivant ▶", style=discord.ButtonStyle.secondary, row=1, disabled=self.page >= self.total_pages)

            async def _prev(inter: Interaction):
                self.page -= 1
                self._build()
                await inter.response.edit_message(embed=self.render_embed(), view=self)

            async def _next(inter: Interaction):
                self.page += 1
                self._build()
                await inter.response.edit_message(embed=self.render_embed(), view=self)

            prev_btn.callback = _prev
            next_btn.callback = _next
            self.add_item(prev_btn)
            self.add_item(indicator)
            self.add_item(next_btn)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.HTTPException, discord.NotFound):
                pass


async def register(bot):
    @bot.tree.command(name="shop", description="Affiche la boutique des rôles disponibles.")
    async def boutique(interaction: Interaction):
        items = await get_shop_items(interaction.guild_id)
        if not items:
            embed = discord.Embed(title="🛒 Boutique vide", description="La boutique est vide pour le moment.", color=discord.Color.orange())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed)
            return

        is_hibiscus = random.random() < 0.001
        color = _HIBISCUS if is_hibiscus else random.choice(_COLORS[:-1])

        numbered_items = [
            (num, role_id, prix, nom, exclusif)
            for num, (_id, role_id, prix, nom, _desc, exclusif) in enumerate(items, start=1)
        ]

        view = ShopView(numbered_items, color, interaction.client.user)
        embed = view.render_embed()
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

        if is_hibiscus:
            await _mark_found(interaction.user.id, "l_hibiscus")
            await interaction.followup.send("🌺 Ta boutique prend la couleur de l'hibiscus. Tu as débloqué un nouveau trophée secret. Utilise `/discoveries` pour le voir.", ephemeral=True)
