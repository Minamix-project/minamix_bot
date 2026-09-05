import discord
from discord import Interaction, Member, app_commands
from discord.ui import Select
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.rp import has_rp_permission, invalidate_cache
from src.utils.views import ExpiringView


async def register(bot):
    @bot.tree.command(name="rpdelete", description="Supprimer un personnage RP")
    @app_commands.describe(user="Utilisateur propriétaire du personnage")
    async def rpdelete(interaction: Interaction, user: Member):
        if not has_rp_permission(interaction.user):
            embed = discord.Embed(title="❌ Permission refusée", color=discord.Color.red())
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
        select = Select(placeholder="Choisir un personnage à supprimer...", options=options)

        async def on_select(inter: Interaction):
            char_id = int(select.values[0])
            char = next((r for r in rows if r[0] == char_id), None)
            if not char:
                await inter.response.send_message("❌ Personnage introuvable.", ephemeral=True)
                return

            _, char_name, char_prefix = char

            db2 = await get_db_connection()
            cursor2 = await db2.cursor()
            await cursor2.execute("DELETE FROM rp_characters WHERE id = %s", (char_id,))
            await db2.commit()
            await cursor2.close()
            db2.close()
            invalidate_cache(inter.guild.id)

            embed = discord.Embed(
                title="✅ Personnage supprimé",
                description=f"**{char_name}** (préfixe `{char_prefix}`) appartenant à {user.mention} a été supprimé.",
                color=discord.Color.green()
            )
            set_bot_footer(embed, inter)
            await inter.response.send_message(embed=embed, ephemeral=True)

        select.callback = on_select
        view = ExpiringView()
        view.add_item(select)

        embed = discord.Embed(
            title=f"🎭 Supprimer un personnage de {user.display_name}",
            description="Sélectionne le personnage à supprimer.",
            color=discord.Color.red()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()
