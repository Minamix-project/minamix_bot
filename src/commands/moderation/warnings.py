import discord
from discord import Interaction, Member, app_commands
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="warnings", description="Voir les avertissements d'un membre (Admin seulement)")
    @app_commands.describe(user="Membre à consulter", page="Page à afficher")
    async def warnings(interaction: Interaction, user: Member, page: int = 1):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(title="❌ Permission refusée", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer()

        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute(
            "SELECT moderator_id, reason, created_at FROM warnings "
            "WHERE user_id = %s AND guild_id = %s ORDER BY created_at DESC",
            (user.id, interaction.guild.id)
        )
        rows = cursor.fetchall()
        cursor.close()
        db.close()

        if not rows:
            embed = discord.Embed(
                title=f"📋 Avertissements — {user.display_name}",
                description="Aucun avertissement.",
                color=discord.Color.green()
            )
            set_bot_footer(embed, interaction)
            await interaction.followup.send(embed=embed)
            return

        embed = discord.Embed(
            title=f"📋 Avertissements — {user.display_name} ({len(rows)})",
            color=discord.Color.orange()
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        page = max(page, 1)
        start = (page - 1) * 10
        for num, (mod_id, reason, created_at) in enumerate(rows[start:start + 10], start=start + 1):
            mod = interaction.guild.get_member(mod_id)
            mod_name = mod.display_name if mod else f"ID {mod_id}"
            embed.add_field(
                name=f"#{num} — <t:{int(created_at.timestamp())}:d> — par {mod_name}",
                value=reason,
                inline=False
            )

        if len(rows) > 10:
            embed.set_footer(text=f"Affichage des 10 derniers sur {len(rows)} au total.")

        set_bot_footer(embed, interaction)
        await interaction.followup.send(embed=embed)
