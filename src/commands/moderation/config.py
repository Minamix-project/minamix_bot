import discord
from discord import Interaction

from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.permissions import admin_only


_CONFIG_LABELS = {
    "logs_channel": "Logs généraux",
    "warn_logs_channel": "Logs des avertissements",
    "afk_logs_channel": "Logs des absences",
    "rp_channel": "Salon RP",
}


async def register(bot):
    @bot.tree.command(name="config", description="Afficher les salons configurés (Admin seulement)")
    @admin_only()
    async def config(interaction: Interaction):
        db = get_db_connection()
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    "SELECT config_key, value FROM guild_config WHERE guild_id = %s ORDER BY config_key",
                    (interaction.guild_id,),
                )
                rows = cursor.fetchall()
        finally:
            db.close()

        embed = discord.Embed(title="⚙️ Salons configurés", color=discord.Color.blurple())
        if not rows:
            embed.description = "Aucun salon n'est configuré sur ce serveur."
        else:
            for key, channel_id in rows:
                label = _CONFIG_LABELS.get(key, key)
                try:
                    channel = interaction.guild.get_channel(int(channel_id))
                except (TypeError, ValueError):
                    channel = None

                value = f"{channel.mention} — **#{channel.name}**" if channel else f"⚠️ Salon introuvable (`{channel_id}`)"
                embed.add_field(name=label, value=value, inline=False)

        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
