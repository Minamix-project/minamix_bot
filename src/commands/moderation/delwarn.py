from src.utils.permissions import admin_only
import discord
from discord import Interaction, Member, app_commands
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.confirm import confirm_action


async def register(bot):
    @bot.tree.command(name="delwarn", description="Supprimer un avertissement par son numéro (Admin seulement)")
    @app_commands.describe(user="Membre concerné", numero="Numéro du warn (visible dans /warnings)")
    @admin_only()
    async def delwarn(interaction: Interaction, user: Member, numero: int):
        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT id, reason, created_at, moderator_id FROM warnings "
            "WHERE user_id = %s AND guild_id = %s ORDER BY created_at DESC",
            (user.id, interaction.guild.id)
        )
        rows = (await cursor.fetchall())
        await cursor.close()
        db.close()

        if numero < 1 or numero > len(rows):
            embed = discord.Embed(
                title="❌ Numéro invalide",
                description=f"{user.display_name} a **{len(rows)}** avertissement(s).",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        warn_id, reason, created_at, moderator_id = rows[numero - 1]

        async def on_confirm(inter: Interaction):
            db2 = await get_db_connection()
            cursor2 = await db2.cursor()
            await cursor2.execute("DELETE FROM warnings WHERE id = %s", (warn_id,))
            await db2.commit()
            await cursor2.close()
            db2.close()

            result_embed = discord.Embed(
                title="✅ Avertissement supprimé",
                description=(
                    f"Warn **#{numero}** de {user.mention} supprimé.\n"
                    f"**Raison :** {reason}\n"
                    f"**Date :** <t:{int(created_at.timestamp())}:d>"
                ),
                color=discord.Color.green()
            )
            set_bot_footer(result_embed, inter)
            await inter.response.edit_message(embed=result_embed, view=None)

        await confirm_action(
            interaction,
            title="🗑️ Confirmer la suppression ?",
            summary_lines=[
                f"**Membre :** {user.mention}",
                f"**Warn :** #{numero}",
                f"**Raison :** {reason}",
                f"**Donné par :** <@{moderator_id}>",
                f"**Date :** <t:{int(created_at.timestamp())}:d>",
            ],
            on_confirm=on_confirm,
            confirm_label="Supprimer",
            confirm_emoji="🗑️",
        )
