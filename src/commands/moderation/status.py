import time
import discord
from discord import Interaction
from src.utils.embed import set_bot_footer
from src.utils.repository_status import WEB_ROOT, get_repository_status

_start_time = time.time()


async def register(bot):
    @bot.tree.command(name="status", description="Afficher le statut et les infos du bot.")
    async def status(interaction: Interaction):
        await interaction.response.defer()

        latency = round(bot.latency * 1000)
        uptime_seconds = int(time.time() - _start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        total_members = sum(g.member_count or 0 for g in bot.guilds)

        embed = discord.Embed(
            title=f"📡 Statut — {bot.user.name}",
            color=discord.Color.green() if latency < 200 else discord.Color.orange(),
        )
        embed.add_field(name="Ping", value=f"`{latency} ms`", inline=True)
        embed.add_field(name="En ligne depuis", value=f"`{uptime_str}`", inline=True)
        embed.add_field(name="Serveurs", value=f"`{len(bot.guilds)}`", inline=True)
        embed.add_field(name="Membres", value=f"`{total_members}`", inline=True)
        embed.add_field(name="Version discord.py", value=f"`{discord.__version__}`", inline=True)

        repository = await get_repository_status()
        stats = repository.stats
        embed.add_field(
            name="📦 Dépôt du bot",
            value=f"[Branche main]({WEB_ROOT}/tree/main) · Lignes non vides des sources et configurations, commentaires inclus.",
            inline=False,
        )
        unavailable = "Indisponible"
        embed.add_field(name="Lignes de code", value=f"{stats.lines:,}".replace(",", " ") if stats else unavailable)
        embed.add_field(name="Fichiers", value=f"{stats.files:,}".replace(",", " ") if stats else unavailable)
        embed.add_field(name="Commits", value=f"{stats.commits:,}".replace(",", " ") if stats else unavailable)
        languages = f"{len(stats.languages)} — " + ", ".join(stats.languages) if stats else unavailable
        embed.add_field(name="Langages", value=languages[:1024], inline=False)
        version = unavailable
        if stats and stats.release_available:
            version = (
                f"[{discord.utils.escape_markdown(stats.release)}]({stats.release_url})"
                if stats.release
                else "Aucune release stable sur main"
            )
        embed.add_field(name="Dernière version (main)", value=version, inline=False)
        if repository.stale:
            embed.add_field(
                name="Actualisation",
                value="GitHub est temporairement indisponible ; dernières statistiques conservées.",
                inline=False,
            )
        elif stats is None:
            embed.add_field(
                name="Actualisation", value="Les statistiques GitHub sont temporairement indisponibles.", inline=False
            )

        if bot.user.avatar:
            embed.set_thumbnail(url=bot.user.avatar.url)

        set_bot_footer(embed, interaction)
        await interaction.followup.send(embed=embed)
