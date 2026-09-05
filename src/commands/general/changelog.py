import asyncio
import json
import logging
from urllib.request import Request, urlopen

import discord
from discord import Interaction

from src.utils.embed import set_bot_footer


def _fetch_releases():
    request = Request("https://api.github.com/repos/Minamix-project/minamix_bot/releases?per_page=5", headers={"Accept": "application/vnd.github+json", "User-Agent": "MinamixBot"})
    with urlopen(request, timeout=8) as response:
        return json.load(response)


async def register(bot):
    @bot.tree.command(name="changelog", description="Afficher les dernières versions du bot")
    async def changelog(interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            releases = await asyncio.to_thread(_fetch_releases)
        except Exception as exc:
            logging.getLogger(__name__).warning("Could not fetch changelog: %s", exc)
            await interaction.followup.send("❌ Impossible de charger les releases GitHub.", ephemeral=True)
            return
        if not releases:
            await interaction.followup.send("Aucune release publiée pour le moment.", ephemeral=True)
            return
        embed = discord.Embed(title="📝 Dernières versions", color=discord.Color.blurple())
        for release in releases:
            notes = (release.get("body") or "Aucune note.").strip()[:700]
            embed.add_field(name=release.get("name") or release["tag_name"], value=f"{notes}\n[Voir sur GitHub]({release['html_url']})", inline=False)
        set_bot_footer(embed, interaction)
        await interaction.followup.send(embed=embed, ephemeral=True)
