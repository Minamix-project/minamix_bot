"""Administrative commands for manually publishing GitHub release devlogs."""

import asyncio

import discord
from discord import app_commands

from src.utils.devlog import (
    DevlogError, NO_MENTIONS, configure_devlog, devlog_emojis, fetch_release_group, publish_devlog, validate_channel,
)
from src.utils.permissions import admin_only


async def register(bot):
    @bot.tree.command(name="setdevlog", description="Définir le salon du devlog du bot (administration).")
    @app_commands.describe(channel="Salon où publier les versions du bot")
    @admin_only()
    async def setdevlog(interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        try:
            validate_channel(channel, interaction.guild, interaction.user)
            await configure_devlog(interaction.guild_id, channel.id)
            major, minor = devlog_emojis(bot, channel)
            await interaction.followup.send(
                f"✅ Devlog configuré dans {channel.mention}.\n"
                f"Majeures : {major} · Mineures : {minor} · Correctifs : `-`.\n"
                "Les correctifs sont ajoutés sous leur version majeure ou mineure. "
                "Lance `/devlog` pour publier ou `/devlog preview:True` pour un aperçu privé. "
                "Sans les emojis personnalisés `kchoc` et `kgun`, les emojis standards sont utilisés.",
                ephemeral=True, allowed_mentions=NO_MENTIONS,
            )
        except DevlogError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)

    @bot.tree.command(name="devlog", description="Publier ou actualiser le devlog depuis les releases GitHub (administration).")
    @admin_only()
    @app_commands.checks.cooldown(1, 15, key=lambda interaction: interaction.guild_id)
    @app_commands.describe(version="Version à publier, par exemple v1.8.3 ; dernière release par défaut",
                           preview="Afficher un aperçu privé sans publier ni modifier le salon")
    async def devlog(interaction: discord.Interaction, version: str | None = None, preview: bool = False):
        await interaction.response.defer(ephemeral=True)
        try:
            async with asyncio.timeout(120):
                releases = await fetch_release_group(version)
                result = await publish_devlog(bot, interaction.guild, interaction.user, releases, preview=preview)
            if preview:
                await interaction.followup.send(
                    f"🔎 Aperçu privé pour <#{result.channel_id}> — {len(result.pages)} message(s). Aucun changement publié.",
                    ephemeral=True, allowed_mentions=NO_MENTIONS,
                )
                for page in result.pages:
                    await interaction.followup.send(page, ephemeral=True, allowed_mentions=NO_MENTIONS,
                                                    suppress_embeds=True)
                return
            url = f"https://discord.com/channels/{interaction.guild_id}/{result.channel_id}/{result.message_ids[0]}"
            status = "Déjà à jour" if not (result.created or result.edited) else "Devlog actualisé"
            await interaction.followup.send(
                f"✅ {status} : {result.created} message(s) créé(s), {result.edited} modifié(s). [Voir le devlog]({url})",
                ephemeral=True, allowed_mentions=NO_MENTIONS,
            )
        except DevlogError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Discord refuse l'accès au devlog. Vérifie les permissions du bot dans le salon.", ephemeral=True)
        except (TimeoutError, discord.HTTPException):
            await interaction.followup.send(
                "❌ Publication interrompue. Réessaie la même commande : les messages retrouvés seront réutilisés.",
                ephemeral=True,
            )
