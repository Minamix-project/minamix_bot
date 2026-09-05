import discord
import logging
from discord import Interaction, Member, app_commands
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.pagination import PaginationView


async def register(bot):
    @bot.tree.command(name="rplist", description="Lister les personnages RP d'un utilisateur")
    @app_commands.describe(user="Utilisateur (laisse vide pour toi-même)", page="Page à afficher")
    async def rplist(interaction: Interaction, user: Member = None, page: int = 1):
        target = user or interaction.user

        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT name, prefix, image_url, created_at FROM rp_characters "
            "WHERE guild_id = %s AND user_id = %s ORDER BY created_at ASC",
            (interaction.guild.id, target.id)
        )
        rows = (await cursor.fetchall())
        await cursor.close()
        db.close()

        if not rows:
            embed = discord.Embed(
                title=f"🎭 Personnages de {target.display_name}",
                description="Aucun personnage créé.",
                color=discord.Color.blurple()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        total_pages = (len(rows) + 9) // 10

        def render(current_page: int) -> discord.Embed:
            embed = discord.Embed(
                title=f"🎭 Personnages de {target.display_name} ({len(rows)})",
                color=discord.Color.blurple(),
            )
            embed.set_thumbnail(url=target.display_avatar.url)
            start = (current_page - 1) * 10
            for name, prefix, image_url, created_at in rows[start:start + 10]:
                embed.add_field(
                    name=name,
                    value=f"Préfixe : `{prefix}`\n[Image]({image_url})\nCréé le <t:{int(created_at.timestamp())}:d>",
                    inline=True,
                )
            set_bot_footer(embed, interaction)
            return embed

        view = PaginationView(interaction.user.id, total_pages, render, page)
        if total_pages > 1:
            await interaction.response.send_message(
                embed=view.current_embed(), view=view, ephemeral=True
            )
            try:
                view.message = await interaction.original_response()
            except discord.HTTPException as exc:
                logging.getLogger(__name__).warning("Could not fetch RP pagination message: %s", exc)
        else:
            await interaction.response.send_message(
                embed=view.current_embed(), ephemeral=True
            )
