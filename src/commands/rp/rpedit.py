from src.utils.permissions import rp_only
import discord
from discord import Interaction, Member, app_commands
from discord.ui import Select, Modal, TextInput
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.rp import has_rp_permission, invalidate_cache
from src.utils.views import ExpiringView


async def register(bot):
    @bot.tree.command(name="rpedit", description="Modifier un personnage RP (nom / préfixe)")
    @app_commands.describe(user="Utilisateur propriétaire du personnage")
    @rp_only()
    async def rpedit(interaction: Interaction, user: Member):
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
        select = Select(placeholder="Choisir un personnage...", options=options)

        async def on_select(inter: Interaction):
            char_id = int(select.values[0])
            char = next((r for r in rows if r[0] == char_id), None)
            if not char:
                await inter.response.send_message("❌ Personnage introuvable.", ephemeral=True)
                return

            _, current_name, current_prefix = char

            class EditModal(Modal, title=f"Modifier {current_name}"):
                new_name = TextInput(
                    label="Nom",
                    default=current_name,
                    max_length=100,
                )
                new_prefix = TextInput(
                    label="Préfixe",
                    default=current_prefix,
                    max_length=20,
                )

                async def on_submit(self, modal_inter: Interaction):
                    name_val = self.new_name.value.strip()
                    prefix_val = self.new_prefix.value.strip()

                    updates = []
                    values = []
                    changes = []

                    if name_val != current_name:
                        updates.append("name = %s")
                        values.append(name_val)
                        changes.append(f"Nom : **{current_name}** → **{name_val}**")
                    if prefix_val != current_prefix:
                        updates.append("prefix = %s")
                        values.append(prefix_val)
                        changes.append(f"Préfixe : `{current_prefix}` → `{prefix_val}`")

                    if not updates:
                        await modal_inter.response.send_message(
                            "Aucune modification détectée.", ephemeral=True
                        )
                        return

                    values.append(char_id)
                    db2 = await get_db_connection()
                    cursor2 = await db2.cursor()
                    try:
                        await cursor2.execute(
                            f"UPDATE rp_characters SET {', '.join(updates)} WHERE id = %s",
                            values
                        )
                        await db2.commit()
                    except Exception as e:
                        await cursor2.close()
                        db2.close()
                        msg = f"Le préfixe `{prefix_val}` est déjà pris." if "Duplicate" in str(e) else str(e)
                        await modal_inter.response.send_message(f"❌ {msg}", ephemeral=True)
                        return

                    await cursor2.close()
                    db2.close()
                    invalidate_cache(modal_inter.guild.id)

                    embed = discord.Embed(
                        title="✅ Personnage modifié",
                        description="\n".join(changes),
                        color=discord.Color.green()
                    )
                    set_bot_footer(embed, modal_inter)
                    await modal_inter.response.send_message(embed=embed, ephemeral=True)

            await inter.response.send_modal(EditModal())

        select.callback = on_select
        view = ExpiringView()
        view.add_item(select)

        embed = discord.Embed(
            title=f"🎭 Modifier un personnage de {user.display_name}",
            description="Sélectionne le personnage à modifier.",
            color=discord.Color.blurple()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()
