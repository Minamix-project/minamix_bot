import discord
from src.utils.db import get_db_connection


async def issue_warn(bot, guild: discord.Guild, user: discord.Member, moderator, reason: str) -> int:
    """Insert warn, DM user, send to logs. Returns total warn count for this user."""
    db = await get_db_connection()
    cursor = await db.cursor()

    await cursor.execute(
        "INSERT INTO warnings (user_id, guild_id, moderator_id, reason) VALUES (%s, %s, %s, %s)",
        (user.id, guild.id, moderator.id if hasattr(moderator, "id") else bot.user.id, reason)
    )
    await db.commit()

    await cursor.execute(
        "SELECT COUNT(*) FROM warnings WHERE user_id = %s AND guild_id = %s",
        (user.id, guild.id)
    )
    total = (await cursor.fetchone())[0]

    await cursor.execute(
        "SELECT value FROM guild_config WHERE guild_id = %s AND config_key = 'warn_logs_channel'",
        (guild.id,)
    )
    logs_row = (await cursor.fetchone())
    await cursor.close()
    db.close()

    # DM the warned user
    mod_name = moderator.display_name if hasattr(moderator, "display_name") else bot.user.name
    try:
        dm_embed = discord.Embed(
            title=f"⚠️ Avertissement — {guild.name}",
            description=(
                f"Tu as reçu un avertissement.\n\n"
                f"**Raison :** {reason}\n"
                f"**Par :** {mod_name}\n\n"
                f"*Total : {total} avertissement(s)*"
            ),
            color=discord.Color.orange()
        )
        if guild.icon:
            dm_embed.set_thumbnail(url=guild.icon.url)
        await user.send(embed=dm_embed)
    except discord.Forbidden:
        pass

    # Send to warn logs channel
    if logs_row:
        channel = bot.get_channel(int(logs_row[0]))
        if channel:
            log_embed = discord.Embed(
                title="⚠️ Avertissement",
                color=discord.Color.orange()
            )
            log_embed.add_field(name="Utilisateur", value=f"{user.mention} (`{user.id}`)", inline=True)
            log_embed.add_field(name="Par", value=f"{mod_name}", inline=True)
            log_embed.add_field(name="Total warns", value=str(total), inline=True)
            log_embed.add_field(name="Raison", value=reason, inline=False)
            log_embed.set_thumbnail(url=user.display_avatar.url)
            await channel.send(embed=log_embed)

    return total
