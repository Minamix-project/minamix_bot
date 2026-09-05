import discord
from discord import Interaction

from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.permissions import admin_only


async def register(bot):
    @bot.tree.command(name="rphealth", description="Check RP characters and image references")
    @admin_only()
    async def rphealth(interaction: Interaction):
        db = await get_db_connection()
        try:
            async with db.cursor() as cursor:
                await cursor.execute(
                    "SELECT name, prefix, image_url, sheet_message_id FROM rp_characters "
                    "WHERE guild_id = %s ORDER BY name",
                    (interaction.guild_id,),
                )
                rows = await cursor.fetchall()
        finally:
            db.close()

        invalid = [
            f"{name} (`{prefix}`)"
            for name, prefix, image_url, _sheet_message_id in rows
            if not image_url or "/ephemeral-attachments/" in image_url
        ]
        legacy = sum(1 for _name, _prefix, image_url, sheet_message_id in rows if image_url and not sheet_message_id)
        lines = [f"Characters: **{len(rows)}**", f"Healthy references: **{len(rows) - len(invalid)}**"]
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
