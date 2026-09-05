from discord import Interaction, Embed
import discord
from src.utils.db import get_db_connection
from src.utils.format import format_amount
from src.utils.embed import set_bot_footer


def _resolve_name(user_id: int) -> str:
    return f"<@{user_id}>"


async def register(bot):
    @bot.tree.command(name="leaderboard", description="Top 10 des utilisateurs les plus riches.")
    async def leaderboard(interaction: Interaction):
        await interaction.response.defer()

        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute(
            "SELECT user_id, balance FROM guild_wallets WHERE guild_id = %s ORDER BY balance DESC LIMIT 100"
            , (interaction.guild_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        db.close()

        if not rows:
            await interaction.followup.send("Aucun utilisateur enregistré.", ephemeral=True)
            return

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        rank = 0
        for user_id, balance in rows:
            if not interaction.guild.get_member(user_id):
                continue
            rank += 1
            prefix = medals.get(rank, f"`#{rank}`")
            name = _resolve_name(user_id)
            lines.append(f"{prefix} {name} — **{format_amount(balance)}💰**")
            if rank == 10:
                break

        embed = Embed(
            title="🏆 Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        set_bot_footer(embed, interaction)
        await interaction.followup.send(embed=embed)
