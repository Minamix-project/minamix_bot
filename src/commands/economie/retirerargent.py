from discord import Interaction, User
from discord import app_commands
import discord
from src.utils.db import get_db_connection
from src.utils.wallet import modify_user_balance
from src.utils.embed import create_balance_embed, set_bot_footer

async def register(bot):
    @bot.tree.command(
        name="removemoney",
        description="Retirer de l'argent à un utilisateur (Admin seulement)"
    )
    @app_commands.describe(
        user="Utilisateur dont retirer de l'argent",
        montant="Montant à retirer"
    )
    async def retirerargent(interaction: Interaction, user: User, montant: int):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Permission refusée",
                description="Vous n'avez pas la permission d'utiliser cette commande.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if montant <= 0:
            embed = discord.Embed(
                title="💢 Montant invalide",
                description="Le montant doit être supérieur à 0.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        db = await get_db_connection()
        new_balance = await modify_user_balance(
            db, interaction.guild_id, user.id, montant, "remove",
            type_="admin_remove", detail=f"par {interaction.user}",
        )

        embed = create_balance_embed(user, new_balance, interaction)
        embed.title = f"💸 {montant} retiré à {user.name}"

        await interaction.response.send_message(embed=embed, ephemeral=True)
        db.close()
