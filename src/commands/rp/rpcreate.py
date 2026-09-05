from src.utils.permissions import admin_only
import discord
from discord import Interaction, Member, app_commands
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.rp import invalidate_cache, normalize_discord_image_url, prefixes_too_close


async def register(bot):
    @bot.tree.command(name="rpcreate", description="Créer un personnage RP pour un utilisateur")
    @app_commands.describe(
        user="Utilisateur propriétaire du personnage",
        name="Nom du personnage",
        prefix="Préfixe pour faire parler le personnage (ex: Aria:)",
        image="Image du personnage (fichier)",
    )
    @admin_only()
    async def rpcreate(
        interaction: Interaction,
        user: Member,
        name: str,
        prefix: str,
        image: discord.Attachment,
    ):
        if not image.content_type or not image.content_type.startswith("image/") or image.size > 8 * 1024 * 1024:
            embed = discord.Embed(
                title="❌ Fichier invalide",
                description="Le fichier joint doit être une image.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        name = name.strip()
        prefix = prefix.strip()
        if not 1 <= len(name) <= 100:
            await interaction.response.send_message("❌ Le nom doit faire entre 1 et 100 caractères.", ephemeral=True)
            return
        if len(prefix) < 1 or len(prefix) > 20:
            embed = discord.Embed(
                title="❌ Préfixe invalide",
                description="Le préfixe doit faire entre 1 et 20 caractères.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        rp_channel = await _get_rp_channel(bot, interaction.guild.id) or interaction.channel

        # Post character sheet with the image file to get a stable CDN URL
        file = await image.to_file()
        sheet_embed = discord.Embed(title=name, color=discord.Color.blurple())
        sheet_embed.set_image(url=f"attachment://{image.filename}")
        sheet_embed.add_field(name="Joueur", value=user.mention, inline=True)
        sheet_embed.add_field(name="Préfixe", value=f"`{prefix}`", inline=True)

        msg = await rp_channel.send(embed=sheet_embed, file=file)
        stable_url = normalize_discord_image_url(msg.attachments[0].url if msg.attachments else image.url)

        db = await get_db_connection()
        cursor = await db.cursor()
        try:
            await cursor.execute(
                "SELECT prefix FROM rp_characters WHERE guild_id = %s",
                (interaction.guild.id,),
            )
            if any(prefixes_too_close(prefix, row[0]) for row in await cursor.fetchall()):
                await cursor.close()
                db.close()
                await msg.delete()
                await interaction.edit_original_response(content="❌ Ce préfixe est trop proche d’un préfixe existant.")
                return
            await cursor.execute(
                "INSERT INTO rp_characters (guild_id, user_id, name, prefix, image_url, sheet_channel_id, sheet_message_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (interaction.guild.id, user.id, name, prefix, stable_url, rp_channel.id, msg.id)
            )
            await db.commit()
            char_id = cursor.lastrowid
        except Exception as e:
            await cursor.close()
            db.close()
            try:
                await msg.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass
            if "Duplicate" in str(e):
                embed = discord.Embed(
                    title="❌ Préfixe déjà utilisé",
                    description=f"Le préfixe `{prefix}` est déjà utilisé sur ce serveur.",
                    color=discord.Color.red()
                )
            else:
                import logging
                logging.getLogger(__name__).exception("Could not create RP character")
                embed = discord.Embed(title="❌ Erreur", description="Une erreur interne est survenue. Réessaie plus tard.", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.edit_original_response(embed=embed)
            return

        await cursor.close()
        db.close()
        invalidate_cache(interaction.guild.id)

        # Update footer with char ID
        sheet_embed.set_footer(text=f"ID personnage : {char_id}")
        await msg.edit(embed=sheet_embed)

        confirm = discord.Embed(
            title="✅ Personnage créé",
            description=f"**{name}** créé pour {user.mention} avec le préfixe `{prefix}`.",
            color=discord.Color.green()
        )
        set_bot_footer(confirm, interaction)
        await interaction.edit_original_response(embed=confirm)


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
