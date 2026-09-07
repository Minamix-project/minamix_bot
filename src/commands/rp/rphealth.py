import discord
from discord import Interaction

from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.rp import image_url_from_message, normalize_discord_image_url
from src.utils.permissions import admin_only


async def register(bot):
    @bot.tree.command(name="rphealth", description="Check RP characters and image references")
    @admin_only()
    async def rphealth(interaction: Interaction):
        db = await get_db_connection()
        try:
            async with db.cursor() as cursor:
                await cursor.execute(
                    "SELECT id, name, prefix, image_url, sheet_channel_id, sheet_message_id FROM rp_characters "
                    "WHERE guild_id = %s ORDER BY name",
                    (interaction.guild_id,),
                )
                rows = await cursor.fetchall()
        finally:
            db.close()

        invalid = []
        legacy = 0
        repairs = []
        for char_id, name, prefix, image_url, sheet_channel_id, sheet_message_id in rows:
            if not image_url or "/ephemeral-attachments/" in image_url:
                invalid.append(f"{name} (`{prefix}`): invalid or ephemeral URL")
                continue
            if not sheet_channel_id or not sheet_message_id:
                legacy += 1
                continue
            channel = bot.get_channel(sheet_channel_id)
            try:
                sheet = await channel.fetch_message(sheet_message_id) if channel else None
                actual = image_url_from_message(sheet) if sheet else None
                expected = normalize_discord_image_url(image_url)
                if actual and actual != expected:
                    repairs.append((actual, char_id))
                elif sheet is None or actual is None:
                    invalid.append(f"{name} (`{prefix}`): image message unavailable")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                invalid.append(f"{name} (`{prefix}`): image message unavailable")

        if repairs:
            db_repair = await get_db_connection()
            try:
                async with db_repair.cursor() as cursor:
                    for image_url, char_id in repairs:
                        await cursor.execute("UPDATE rp_characters SET image_url = %s WHERE id = %s", (image_url, char_id))
                await db_repair.commit()
            finally:
                db_repair.close()

        lines = [f"Characters: **{len(rows)}**", f"Healthy references: **{len(rows) - len(invalid) - legacy}**"]
        if repairs:
            lines.append(f"Repaired database image references: **{len(repairs)}**.")
        if invalid:
            lines.append("Needs image re-upload:\n" + "\n".join(f"- {item}" for item in invalid[:20]))
            if len(invalid) > 20:
                lines.append(f"…and {len(invalid) - 20} more.")
        else:
            lines.append("All image references are permanent message attachments.")
        if legacy:
            lines.append(f"Legacy characters without a tracked sheet message: **{legacy}**.")

        embed = discord.Embed(title="🎭 RP health", description="\n".join(lines), color=discord.Color.green() if not invalid else discord.Color.orange())
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
