from discord import Interaction, app_commands
from discord.ui import Button
import discord
from src.utils.shop import get_shop_items
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.views import ExpiringView


async def register(bot):
    @bot.tree.command(
        name="removeitem",
        description="Supprimer un article de la boutique (Admin seulement)"
    )
    @app_commands.describe(numero="Numéro de l'article affiché dans /shop")
    async def supprimergrade(interaction: Interaction, numero: int):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Permission refusée",
                description="Vous n'avez pas la permission d'utiliser cette commande.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        items = await get_shop_items(interaction.guild_id)

        if numero < 1 or numero > len(items):
            embed = discord.Embed(
                title="❌ Numéro invalide",
                description=f"Il n'y a que **{len(items)}** article(s) dans la boutique.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        actual_id, role_id, _prix, role_name, *__ = items[numero - 1]

        embed = discord.Embed(
            title="🗑️ Confirmer la suppression ?",
            description=f"Tu t'apprêtes à supprimer **#{numero} — {role_name}** (<@&{role_id}>) de la boutique.",
            color=discord.Color.orange()
        )
        set_bot_footer(embed, interaction)

        view = ExpiringView(timeout=30)
        confirm_btn = Button(label="Supprimer", style=discord.ButtonStyle.red, emoji="🗑️")
        cancel_btn = Button(label="Annuler", style=discord.ButtonStyle.grey, emoji="❌")

        async def confirm_callback(inter: Interaction):
            db2 = await get_db_connection()
            cursor2 = await db2.cursor()
            await cursor2.execute("DELETE FROM guild_boutique_roles WHERE id = %s", (actual_id,))
            await db2.commit()
            await cursor2.close()
            db2.close()

            result_embed = discord.Embed(
                title="✅ Article supprimé",
                description=f"L'article **#{numero} — {role_name}** (<@&{role_id}>) a été supprimé de la boutique.",
                color=discord.Color.green()
            )
            set_bot_footer(result_embed, inter)
            await inter.response.edit_message(embed=result_embed, view=None)

        async def cancel_callback(inter: Interaction):
            cancel_embed = discord.Embed(title="❌ Suppression annulée", color=discord.Color.red())
            set_bot_footer(cancel_embed, inter)
            await inter.response.edit_message(embed=cancel_embed, view=None)

        confirm_btn.callback = confirm_callback
        cancel_btn.callback = cancel_callback
        view.add_item(confirm_btn)
        view.add_item(cancel_btn)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()
