from discord import Interaction
from src.utils.db import get_db_connection
from src.utils.balance import get_user_balance
from src.utils.embed import create_balance_embed

async def register(bot):
    @bot.tree.command(name="balance", description="Voir votre solde 💰")
    async def solde(interaction: Interaction):
        db = await get_db_connection()
        balance = await get_user_balance(db, interaction.guild_id, interaction.user.id)
        embed = create_balance_embed(interaction.user, balance, interaction)

        await interaction.response.send_message(embed=embed, ephemeral=False)

        db.close()