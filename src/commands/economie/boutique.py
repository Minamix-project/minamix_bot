import random
from discord import Interaction, Embed
import discord
from src.utils.shop import get_shop_items
from src.utils.format import format_amount
from src.utils.embed import set_bot_footer
from src.utils.reactions import EGGS, _mark_found

_COLORS = [
    0x3498DB,  # bleu
    0x2ECC71,  # vert
    0x9B59B6,  # violet
    0xE67E22,  # orange
    0xB5264C,  # hibiscus
]
_HIBISCUS = 0xB5264C


async def register(bot):
    @bot.tree.command(
        name="shop",
        description="Affiche la boutique des rôles disponibles."
    )
    async def boutique(interaction: Interaction):
        items = await get_shop_items(interaction.guild_id)

        if not items:
            embed = discord.Embed(
                title="🛒 Boutique vide",
                description="La boutique est vide pour le moment.",
                color=discord.Color.orange()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed)
            return

        is_hibiscus = random.random() < 0.001
        color = _HIBISCUS if is_hibiscus else random.choice(_COLORS[:-1])

        standard = [(num, r, p, n) for num, (_, r, p, n, _d, ex) in enumerate(items, start=1) if not ex]
        exclusifs = [(num, r, p, n) for num, (_, r, p, n, _d, ex) in enumerate(items, start=1) if ex]

        lines = []
        for num, role_id, prix, nom in standard:
            lines.append(f"》 **#{num}** — {format_amount(prix)}💰 : <@&{role_id}>")

        if exclusifs:
            lines.append("")
            lines.append("★―――――――――| Rôles exclusifs |―――――――――★")
            lines.append("")
            for num, role_id, prix, nom in exclusifs:
                lines.append(f"》 **#{num}** — {format_amount(prix)}💰 : <@&{role_id}>")

        embed = Embed(
            title="🛍️ Boutique",
            description="\n".join(lines) + "\n\n*Utilise `/buy <numéro>` pour acheter.*",
            color=color
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed)

        if is_hibiscus:
            await _mark_found(interaction.user.id, "l_hibiscus")
            await interaction.followup.send(
                "🌺 Ta boutique prend la couleur de l'hibiscus. Tu as débloqué un nouveau trophée secret. Utilise `/discoveries` pour le voir.",
                ephemeral=True
            )
