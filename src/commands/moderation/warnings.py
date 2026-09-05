import discord
from discord import Interaction, Member, app_commands
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.pagination import PaginationView


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

        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT moderator_id, reason, created_at FROM warnings "
            "WHERE user_id = %s AND guild_id = %s ORDER BY created_at DESC",
            (user.id, interaction.guild.id)
        )
        rows = (await cursor.fetchall())
        await cursor.close()
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

        total_pages = (len(rows) + 9) // 10

        def render(current_page: int) -> discord.Embed:
            embed = discord.Embed(
                title=f"📋 Avertissements — {user.display_name} ({len(rows)})",
                color=discord.Color.orange(),
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            start = (current_page - 1) * 10
            for num, (mod_id, reason, created_at) in enumerate(rows[start:start + 10], start=start + 1):
                mod = interaction.guild.get_member(mod_id)
                mod_name = mod.display_name if mod else f"ID {mod_id}"
                embed.add_field(
                    name=f"#{num} — <t:{int(created_at.timestamp())}:d> — par {mod_name}",
                    value=reason,
                    inline=False,
                )
            set_bot_footer(embed, interaction)
            return embed

        view = PaginationView(interaction.user.id, total_pages, render, page)
        view.message = await interaction.followup.send(
            embed=view.current_embed(), view=view if total_pages > 1 else None, wait=True
        )
