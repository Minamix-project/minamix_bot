from src.utils.permissions import admin_only
import discord
from discord import Interaction, Member, app_commands
from discord.ui import Select
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.rp import invalidate_cache, normalize_discord_image_url
from src.utils.views import ExpiringView


async def register(bot):
    @bot.tree.command(name="rpimage", description="Changer l'image d'un personnage RP")
    @app_commands.describe(
        user="Utilisateur propriétaire du personnage",
        image="Nouvelle image (fichier)",
    )
    @admin_only()
    async def rpimage(interaction: Interaction, user: Member, image: discord.Attachment):
        if not image.content_type or not image.content_type.startswith("image/"):
            embed = discord.Embed(
                title="❌ Fichier invalide",
                description="Le fichier joint doit être une image.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT id, name, prefix FROM rp_characters WHERE guild_id = %s AND user_id = %s ORDER BY created_at ASC",
            (interaction.guild.id, user.id)
        )
        rows = (await cursor.fetchall())
        await cursor.close()
        db.close()

        if not rows:
            embed = discord.Embed(
                title="❌ Aucun personnage",
                description=f"{user.display_name} n'a aucun personnage sur ce serveur.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        options = [
            discord.SelectOption(label=name, value=str(char_id), description=f"Préfixe : {prefix}")
            for char_id, name, prefix in rows
        ]
        select = Select(placeholder="Choisir un personnage...", options=options)

        async def on_select(inter: Interaction):
            char_id = int(select.values[0])
            char = next((r for r in rows if r[0] == char_id), None)
            if not char:
                await inter.response.send_message("❌ Personnage introuvable.", ephemeral=True)
                return

            _, char_name, _ = char
            await inter.response.defer(ephemeral=True)

            rp_channel = await _get_rp_channel(bot, inter.guild.id) or inter.channel
            file = await image.to_file()
            msg = await rp_channel.send(
                content=f"*Mise à jour de l'image de **{char_name}** :*",
                file=file
            )
            stable_url = normalize_discord_image_url(msg.attachments[0].url if msg.attachments else image.url)

            db2 = await get_db_connection()
            cursor2 = await db2.cursor()
            await cursor2.execute(
                "UPDATE rp_characters SET image_url = %s, sheet_channel_id = %s, sheet_message_id = %s WHERE id = %s",
                (stable_url, rp_channel.id, msg.id, char_id)
            )
            await db2.commit()
            await cursor2.close()
            db2.close()
            invalidate_cache(inter.guild.id)

            embed = discord.Embed(
                title="✅ Image mise à jour",
                description=f"L'image de **{char_name}** a été mise à jour.",
                color=discord.Color.green()
            )
            set_bot_footer(embed, inter)
            await inter.edit_original_response(embed=embed)

        select.callback = on_select
        view = ExpiringView(owner_id=interaction.user.id)
        view.add_item(select)

        embed = discord.Embed(
            title=f"🎭 Changer l'image — {user.display_name}",
            description="Sélectionne le personnage à mettre à jour.",
            color=discord.Color.blurple()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def _get_rp_channel(bot, guild_id: int):
    db = await get_db_connection()
    cursor = await db.cursor()
    await cursor.execute(
        "SELECT value FROM guild_config WHERE guild_id = %s AND config_key = 'rp_channel'",
        (guild_id,)
    )
    row = (await cursor.fetchone())
    await cursor.close()
    db.close()
    if row:
        return bot.get_channel(int(row[0]))
    return None
