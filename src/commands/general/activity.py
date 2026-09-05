from src.utils.permissions import admin_only
import discord
from discord import Interaction, Member, app_commands
from datetime import datetime, timezone
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="activity", description="Voir l'activité d'un membre (Admin seulement).")
    @app_commands.describe(user="Membre à consulter")
    @admin_only()
    async def activity(interaction: Interaction, user: Member):
        await interaction.response.defer()

        db = await get_db_connection()
        cursor = await db.cursor()

        await cursor.execute(
            "SELECT last_seen FROM guild_member_activity WHERE guild_id = %s AND user_id = %s",
            (interaction.guild_id, user.id),
        )
        seen_row = (await cursor.fetchone())

        await cursor.execute(
            "SELECT reason, start_time, end_time FROM afk_users WHERE user_id = %s AND guild_id = %s",
            (user.id, interaction.guild.id)
        )
        afk_row = (await cursor.fetchone())

        await cursor.close()
        db.close()

        embed = discord.Embed(
            title=f"📋 Activité — {user.display_name}",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        # Discord info
        embed.add_field(
            name="Compte créé le",
            value=f"<t:{int(user.created_at.timestamp())}:D>",
            inline=True
        )
        embed.add_field(
            name="A rejoint le serveur",
            value=f"<t:{int(user.joined_at.timestamp())}:D>" if user.joined_at else "Inconnu",
            inline=True
        )

        # Last seen
        if seen_row and seen_row[0]:
            last_seen: datetime = seen_row[0]
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            embed.add_field(
                name="Dernière activité",
                value=f"<t:{int(last_seen.timestamp())}:R>",
                inline=False
            )
        else:
            embed.add_field(name="Dernière activité", value="Aucune donnée", inline=False)

        # AFK status
        if afk_row:
            reason, start_time, end_time = afk_row
            end_str = f"<t:{int(end_time.timestamp())}:f>" if end_time else "indéfinie"
            embed.add_field(
                name="💤 Absent(e)",
                value=f"Raison : **{reason}**\nFin prévue : {end_str}",
                inline=False
            )
        else:
            embed.add_field(name="Statut", value="✅ Présent(e)", inline=False)

        set_bot_footer(embed, interaction)
        await interaction.followup.send(embed=embed)
