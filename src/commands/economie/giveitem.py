from discord import Interaction, Member, app_commands
import discord
from src.utils.shop import get_shop_items
from src.utils.embed import set_bot_footer
from src.utils.balance import get_user_balance
from src.utils.wallet import modify_user_balance
from src.utils.format import format_amount
from src.utils.db import get_db_connection


async def register(bot):
    @bot.tree.command(
        name="giveitem",
        description="Donner un article de la boutique à un utilisateur (Admin seulement)"
    )
    @app_commands.describe(
        numero="Numéro de l'article affiché dans /shop",
        user="Utilisateur qui reçoit le rôle",
        deduire="Déduire le prix du solde du receveur (Non par défaut)"
    )
    @app_commands.choices(deduire=[
        app_commands.Choice(name="Non (gratuit)", value=0),
        app_commands.Choice(name="Oui (déduit du solde)", value=1),
    ])
    async def giveitem(interaction: Interaction, numero: int, user: Member, deduire: int = 0):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(title="❌ Permission refusée", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        items = await get_shop_items(interaction.guild_id)

        if numero < 1 or numero > len(items):
            embed = discord.Embed(
                title="❌ Numéro invalide",
                description=f"Il n'y a que **{len(items)}** article(s) dans la boutique.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        _, role_id, prix, nom, *__ = items[numero - 1]

        role = interaction.guild.get_role(int(role_id))
        if not role:
            embed = discord.Embed(
                title="❌ Rôle introuvable",
                description="Le rôle associé à cet article n'existe plus sur le serveur.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if role in user.roles:
            embed = discord.Embed(
                title="⚠️ Rôle déjà possédé",
                description=f"{user.mention} a déjà <@&{role_id}>.",
                color=discord.Color.orange()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if deduire:
            db = await get_db_connection()
            balance = await get_user_balance(db, interaction.guild_id, user.id)
            if balance < prix:
                embed = discord.Embed(
                    title="❌ Solde insuffisant",
                    description=(
                        f"{user.mention} a **{format_amount(balance)}💰** "
                        f"mais cet article coûte **{format_amount(prix)}💰**."
                    ),
                    color=discord.Color.red()
                )
                set_bot_footer(embed, interaction)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                db.close()
                return
            await modify_user_balance(db, interaction.guild_id, user.id, prix, "remove")
            db.close()

        try:
            await user.add_roles(role)
        except discord.Forbidden:
            embed = discord.Embed(
                title="❌ Permission insuffisante",
                description="Le bot n'a pas la permission d'attribuer ce rôle.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        desc = f"{user.mention} a reçu <@&{role_id}> (**#{numero} — {nom}**)."
        if deduire:
            desc += f"\n**{format_amount(prix)}💰** déduit de son solde."

        embed = discord.Embed(
            title="✅ Rôle attribué",
            description=desc,
            color=discord.Color.green()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed)
