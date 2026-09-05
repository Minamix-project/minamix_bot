from discord import Interaction, Role
from discord import app_commands
import discord
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.format import format_amount


async def register(bot):
    @bot.tree.command(
        name="additem",
        description="Ajouter un rôle à la boutique (Admin seulement)"
    )
    @app_commands.describe(
        role="Le rôle Discord à ajouter",
        prix="Prix en coins",
        nom="Nom affiché dans la boutique",
        exclusif="Rôle exclusif ? (affiché séparément dans la boutique)",
        description="Description du rôle (optionnel)"
    )
    @app_commands.choices(exclusif=[
        app_commands.Choice(name="Non (défaut)", value=0),
        app_commands.Choice(name="Oui", value=1),
    ])
    async def addgrade(
        interaction: Interaction,
        role: Role,
        prix: int,
        nom: str,
        exclusif: int = 0,
        description: str = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Permission refusée",
                description="Vous n'avez pas la permission d'utiliser cette commande.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if prix <= 0:
            embed = discord.Embed(
                title="💢 Prix invalide",
                description="Le prix doit être supérieur à 0.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        db = get_db_connection()
        cursor = db.cursor()
        try:
            cursor.execute(
                "INSERT INTO guild_boutique_roles (guild_id, role_id, prix, nom, description, exclusif) VALUES (%s, %s, %s, %s, %s, %s)",
                (interaction.guild_id, role.id, prix, nom, description, exclusif)
            )
            db.commit()

            label = "exclusif" if exclusif else "standard"
            embed = discord.Embed(
                title="✅ Article ajouté",
                description=(
                    f"**{nom}** (<@&{role.id}>) ajouté à la boutique pour **{format_amount(prix)}💰**\n"
                    f"Type : **{label}**"
                ),
                color=discord.Color.green()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Erreur",
                description=f"Une erreur s'est produite : {e}",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        finally:
            cursor.close()
            db.close()
