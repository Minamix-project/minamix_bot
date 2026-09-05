from src.utils.permissions import admin_only
import discord
from discord import Interaction, Member, app_commands
from discord.ui import Select
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.rp import invalidate_cache
from src.utils.views import ExpiringView
from src.utils.confirm import confirm_action


async def register(bot):
    @bot.tree.command(name="rpdelete", description="Supprimer un personnage RP")
    @app_commands.describe(user="Utilisateur propriétaire du personnage")
    @admin_only()
    async def rpdelete(interaction: Interaction, user: Member):
        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT id, name, prefix, nax_balance, created_at FROM rp_characters "
            "WHERE guild_id = %s AND user_id = %s ORDER BY created_at ASC",
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
            for char_id, name, prefix, *_rest in rows
        ]
        select = Select(placeholder="Choisir un personnage à supprimer...", options=options)

        async def on_select(inter: Interaction):
            char_id = int(select.values[0])
            char = next((r for r in rows if r[0] == char_id), None)
            if not char:
                await inter.response.send_message("❌ Personnage introuvable.", ephemeral=True)
                return

            _, char_name, char_prefix, nax_balance, created_at = char

            async def on_confirm(confirm_inter: Interaction):
                db2 = await get_db_connection()
                cursor2 = await db2.cursor()
                await cursor2.execute("DELETE FROM rp_characters WHERE id = %s", (char_id,))
                await db2.commit()
                await cursor2.close()
                db2.close()
                invalidate_cache(confirm_inter.guild.id)

                result_embed = discord.Embed(
                    title="✅ Personnage supprimé",
                    description=f"**{char_name}** (préfixe `{char_prefix}`) appartenant à {user.mention} a été supprimé.",
                    color=discord.Color.green()
                )
                set_bot_footer(result_embed, confirm_inter)
                await confirm_inter.response.edit_message(embed=result_embed, view=None)

            await confirm_action(
                inter,
                title="🗑️ Confirmer la suppression ?",
                summary_lines=[
                    f"**Personnage :** {char_name} (préfixe `{char_prefix}`)",
                    f"**Propriétaire :** {user.mention}",
                    f"**Solde nax :** {nax_balance}",
                    f"**Créé le :** <t:{int(created_at.timestamp())}:d>",
                ],
                on_confirm=on_confirm,
                confirm_label="Supprimer",
                confirm_emoji="🗑️",
            )

        select.callback = on_select
        view = ExpiringView(owner_id=interaction.user.id)
        view.add_item(select)

        embed = discord.Embed(
            title=f"🎭 Supprimer un personnage de {user.display_name}",
            description="Sélectionne le personnage à supprimer.",
            color=discord.Color.red()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()
