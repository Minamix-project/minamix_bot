import discord
from discord import Interaction, Member, app_commands
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="delwarn", description="Supprimer un avertissement par son numéro (Admin seulement)")
    @app_commands.describe(user="Membre concerné", numero="Numéro du warn (visible dans /warnings)")
    async def delwarn(interaction: Interaction, user: Member, numero: int):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(title="❌ Permission refusée", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT id, reason, created_at FROM warnings "
            "WHERE user_id = %s AND guild_id = %s ORDER BY created_at DESC",
            (user.id, interaction.guild.id)
        )
        rows = (await cursor.fetchall())

        if numero < 1 or numero > len(rows):
            await cursor.close()
            db.close()
            embed = discord.Embed(
                title="❌ Numéro invalide",
                description=f"{user.display_name} a **{len(rows)}** avertissement(s).",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        warn_id, reason, created_at = rows[numero - 1]
        await cursor.execute("DELETE FROM warnings WHERE id = %s", (warn_id,))
        await db.commit()
        await cursor.close()
        db.close()

        embed = discord.Embed(
            title="✅ Avertissement supprimé",
            description=(
                f"Warn **#{numero}** de {user.mention} supprimé.\n"
                f"**Raison :** {reason}\n"
                f"**Date :** <t:{int(created_at.timestamp())}:d>"
            ),
            color=discord.Color.green()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
