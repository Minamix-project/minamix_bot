from src.utils.permissions import admin_only
import discord
from discord import Interaction, app_commands
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="setrpchannel", description="Définir le channel d'annonce des personnages RP (Admin)")
    @app_commands.describe(channel="Channel où les fiches RP seront postées")
    @admin_only()
    async def setrpchannel(interaction: Interaction, channel: discord.TextChannel):
        bot_member = interaction.guild.me
        if bot_member is None:
            await interaction.response.send_message("❌ Unable to resolve the bot member in this server.", ephemeral=True)
            return
        channel_permissions = channel.permissions_for(bot_member)
        required = {
            "send_messages": channel_permissions.send_messages,
            "embed_links": channel_permissions.embed_links,
            "attach_files": channel_permissions.attach_files,
            "manage_messages": channel_permissions.manage_messages,
        }
        missing = [name for name, allowed in required.items() if not allowed]
        if missing:
            await interaction.response.send_message(
                f"❌ Missing bot permissions in {channel.mention}: {', '.join(missing)}.", ephemeral=True
            )
            return
        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "INSERT INTO guild_config (guild_id, config_key, value) VALUES (%s, 'rp_channel', %s) "
            "ON DUPLICATE KEY UPDATE value = VALUES(value)",
            (interaction.guild.id, str(channel.id))
        )
        await db.commit()
        await cursor.close()
        db.close()

        public_warning = ""
        if channel.permissions_for(interaction.guild.default_role).send_messages:
            public_warning = "\n\n⚠️ This channel is writable by @everyone. Use a restricted archive channel to protect image sheets."
        embed = discord.Embed(
            title="✅ Channel RP défini",
            description=f"Les fiches de personnages seront postées dans {channel.mention}.{public_warning}",
            color=discord.Color.green()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
