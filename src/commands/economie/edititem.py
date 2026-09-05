from discord import Interaction, app_commands
import discord
from src.utils.shop import get_shop_items
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.format import format_amount


async def register(bot):
    @bot.tree.command(
        name="edititem",
        description="Modifier un article de la boutique (Admin seulement)"
    )
    @app_commands.describe(
        numero="Numéro de l'article affiché dans /shop",
        prix="Nouveau prix en coins",
        nom="Nouveau nom affiché",
        description="Nouvelle description",
        exclusif="Changer le statut exclusif",
    )
    @app_commands.choices(exclusif=[
        app_commands.Choice(name="Non", value=0),
        app_commands.Choice(name="Oui", value=1),
    ])
    async def edititem(
        interaction: Interaction,
        numero: int,
        prix: int = None,
        nom: str = None,
        description: str = None,
        exclusif: int = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(title="❌ Permission refusée", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        items = get_shop_items(interaction.guild_id)

        if numero < 1 or numero > len(items):
            embed = discord.Embed(
                title="❌ Numéro invalide",
                description=f"Il n'y a que **{len(items)}** article(s) dans la boutique.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        actual_id, role_id, old_prix, old_nom, old_desc, old_excl = items[numero - 1]

        if prix is None and nom is None and description is None and exclusif is None:
            embed = discord.Embed(
                title="❌ Aucun changement",
                description="Tu n'as fourni aucun paramètre à modifier.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        new_prix = prix if prix is not None else old_prix
        new_nom = nom if nom is not None else old_nom
        new_desc = description if description is not None else old_desc
        new_excl = exclusif if exclusif is not None else old_excl

        if prix is not None and prix <= 0:
            embed = discord.Embed(title="💢 Prix invalide", description="Le prix doit être supérieur à 0.", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute(
            "UPDATE guild_boutique_roles SET prix = %s, nom = %s, description = %s, exclusif = %s WHERE id = %s",
            (new_prix, new_nom, new_desc, new_excl, actual_id)
        )
        db.commit()
        cursor.close()
        db.close()

        changes = []
        if prix is not None:
            changes.append(f"Prix : **{format_amount(old_prix)}💰** → **{format_amount(new_prix)}💰**")
        if nom is not None:
            changes.append(f"Nom : **{old_nom}** → **{new_nom}**")
        if description is not None:
            changes.append(f"Description mise à jour")
        if exclusif is not None:
            changes.append(f"Exclusif : **{'Oui' if new_excl else 'Non'}**")

        embed = discord.Embed(
            title="✅ Article modifié",
            description=f"**#{numero} — <@&{role_id}>**\n\n" + "\n".join(changes),
            color=discord.Color.green()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
