from discord import Interaction, Embed, app_commands
import discord
from discord.ui import Select
from src.utils.format import format_amount
from src.utils.embed import set_bot_footer
from src.utils.views import ExpiringView
from src.utils.shop import get_shop_items, item_autocomplete
from src.utils.purchase import show_purchase_confirmation


async def register(bot):
    @bot.tree.command(name="buy", description="Acheter un rôle dans la boutique.")
    @app_commands.describe(numero="Article à acheter (laisser vide pour voir la liste)")
    @app_commands.autocomplete(numero=item_autocomplete)
    async def buy(interaction: Interaction, numero: str = None):
        items = await get_shop_items(interaction.guild_id)

        if not items:
            await interaction.response.send_message("La boutique est vide.", ephemeral=True)
            return

        if numero is not None:
            try:
                numero_int = int(numero)
            except ValueError:
                numero_int = -1
            if numero_int < 1 or numero_int > len(items):
                embed = Embed(
                    title="❌ Numéro invalide",
                    description=f"Il n'y a que **{len(items)}** article(s) dans la boutique.",
                    color=discord.Color.red()
                )
                set_bot_footer(embed, interaction)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            item_id, role_id, prix, nom_role, *__ = items[numero_int - 1]
            await show_purchase_confirmation(interaction, item_id, role_id, prix, nom_role, edit=False)
            return

        options = [
            discord.SelectOption(
                label=f"#{num} — {nom}",
                value=str(num),
                description=f"{format_amount(prix)}💰"
            )
            for num, (_, role_id, prix, nom, *__) in enumerate(items, start=1)
        ][:25]

        select = Select(placeholder="Choisis un article...", options=options)

        async def callback(inter: Interaction):
            num = int(select.values[0])
            item_id, role_id, prix, nom_role, *__ = items[num - 1]
            await show_purchase_confirmation(inter, item_id, role_id, prix, nom_role, edit=True)

        select.callback = callback
        view = ExpiringView(owner_id=interaction.user.id)
        view.add_item(select)
        await interaction.response.send_message("Quel article veux-tu acheter ?", view=view, ephemeral=True)
        view.message = await interaction.original_response()
