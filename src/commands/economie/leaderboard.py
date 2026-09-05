from discord import Interaction, Embed, app_commands
import discord
from src.utils.db import get_db_connection
from src.utils.format import format_amount
from src.utils.embed import set_bot_footer
from src.utils.pagination import PaginationView


def _resolve_name(user_id: int) -> str:
    return f"<@{user_id}>"


async def register(bot):
    @bot.tree.command(name="leaderboard", description="Top 10 des utilisateurs les plus riches.")
    @app_commands.describe(page="Page à afficher")
    async def leaderboard(interaction: Interaction, page: int = 1):
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

        rows = [row for row in rows if interaction.guild.get_member(row[0])]
        if not rows:
            await interaction.followup.send("Aucun membre du serveur n'est classé.", ephemeral=True)
            return

        total_pages = (len(rows) + 9) // 10

        def render(current_page: int) -> Embed:
            start = (current_page - 1) * 10
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            lines = []
            for rank, (user_id, balance) in enumerate(rows[start:start + 10], start=start + 1):
                prefix = medals.get(rank, f"`#{rank}`")
                lines.append(f"{prefix} {_resolve_name(user_id)} — **{format_amount(balance)}💰**")
            embed = Embed(
                title="🏆 Classement des plus riches",
                description="\n".join(lines),
                color=discord.Color.gold(),
            )
            set_bot_footer(embed, interaction)
            return embed

        view = PaginationView(interaction.user.id, total_pages, render, page)
        view.message = await interaction.followup.send(
            embed=view.current_embed(), view=view if total_pages > 1 else None, wait=True
        )
