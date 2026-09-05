from discord import Interaction, app_commands
import discord
from src.utils.shop import get_shop_items, item_autocomplete
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.format import format_amount
from src.utils.confirm import confirm_action


async def register(bot):
    @bot.tree.command(
        name="removeitem",
        description="Supprimer un article de la boutique (Admin seulement)"
    )
    @app_commands.describe(numero="Article à supprimer")
    @app_commands.autocomplete(numero=item_autocomplete)
    async def supprimergrade(interaction: Interaction, numero: str):
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

        try:
            numero_int = int(numero)
        except ValueError:
            numero_int = -1

        if numero_int < 1 or numero_int > len(items):
            embed = discord.Embed(
                title="❌ Numéro invalide",
                description=f"Il n'y a que **{len(items)}** article(s) dans la boutique.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        numero = numero_int
        actual_id, role_id, prix, role_name, description, exclusif = items[numero - 1]

        async def on_confirm(inter: Interaction):
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

        await confirm_action(
            interaction,
            title="🗑️ Confirmer la suppression ?",
            summary_lines=[
                f"**Article :** #{numero} — {role_name}",
                f"**Rôle :** <@&{role_id}>",
                f"**Prix :** {format_amount(prix)}💰",
                f"**Description :** {description or '*aucune*'}",
                f"**Exclusif :** {'Oui' if exclusif else 'Non'}",
            ],
            on_confirm=on_confirm,
            confirm_label="Supprimer",
            confirm_emoji="🗑️",
        )
