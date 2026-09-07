import discord
from discord import Interaction, app_commands

from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.permissions import admin_only


async def register(bot):
    @bot.tree.command(name="rpmaintenance", description="Enable or disable RP messages")
    @app_commands.describe(enabled="Pause RP webhook messages")
    @admin_only()
    async def rpmaintenance(interaction: Interaction, enabled: bool):
        db = await get_db_connection()
        try:
            async with db.cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO guild_config (guild_id, config_key, value) VALUES (%s, 'rp_maintenance', %s) "
                    "ON DUPLICATE KEY UPDATE value = VALUES(value)",
                    (interaction.guild_id, "1" if enabled else "0"),
                )
            await db.commit()
        finally:
            db.close()
        embed = discord.Embed(
            title="🛠️ RP maintenance",
            description="RP messages are now paused." if enabled else "RP messages are active again.",
            color=discord.Color.orange() if enabled else discord.Color.green(),
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
