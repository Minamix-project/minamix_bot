from src.utils.permissions import admin_only
import discord
from discord import Interaction
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="absents", description="Liste des membres absents (Admin seulement)")
    @admin_only()
    async def absents(interaction: Interaction):
        await interaction.response.defer()

        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT user_id, start_time, end_time FROM afk_users "
            "WHERE guild_id = %s ORDER BY start_time ASC",
            (interaction.guild.id,)
        )
        rows = (await cursor.fetchall())
        await cursor.close()
        db.close()

        if not rows:
            embed = discord.Embed(
                title="📋 Absents",
                description="Aucun membre absent en ce moment.",
                color=discord.Color.green()
            )
            set_bot_footer(embed, interaction)
            await interaction.followup.send(embed=embed)
            return

        lines = []
        for user_id, start_time, end_time in rows:
            start_str = f"<t:{int(start_time.timestamp())}:d>"
            end_str = f"<t:{int(end_time.timestamp())}:d>" if end_time else "?"
            lines.append(f"<@{user_id}> — {start_str} → {end_str}")

        embed = discord.Embed(
            title=f"📋 Absents — {len(rows)} membre(s)",
            description="\n".join(lines),
            color=discord.Color.greyple()
        )
        set_bot_footer(embed, interaction)
        await interaction.followup.send(embed=embed)
