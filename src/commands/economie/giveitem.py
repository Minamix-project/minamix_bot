import discord
import logging
from discord import Interaction, Member, app_commands

from src.utils.db import get_db_connection
from src.utils.economy_config import get_guild_economy_config
from src.utils.embed import set_bot_footer
from src.utils.format import format_amount
from src.utils.permissions import admin_only
from src.utils.shop import get_shop_items, item_autocomplete
from src.utils.transactions import record_transaction


async def register(bot):
    @bot.tree.command(
        name="giveitem",
        description="Donner un article de la boutique à un utilisateur (Admin seulement)",
    )
    @app_commands.describe(
        numero="Article à donner",
        user="Utilisateur qui reçoit le rôle",
        deduire="Déduire le prix du solde du receveur (Non par défaut)",
    )
    @app_commands.choices(
        deduire=[
            app_commands.Choice(name="Non (gratuit)", value=0),
            app_commands.Choice(name="Oui (déduit du solde)", value=1),
        ]
    )
    @app_commands.autocomplete(numero=item_autocomplete)
    @admin_only()
    async def giveitem(
        interaction: Interaction, numero: str, user: Member, deduire: int = 0
    ):
        items = await get_shop_items(interaction.guild_id)

        try:
            numero_int = int(numero)
        except ValueError:
            numero_int = -1

        if numero_int < 1 or numero_int > len(items):
            embed = discord.Embed(
                title="❌ Numéro invalide",
                description=f"Il n’y a que **{len(items)}** article(s) dans la boutique.",
                color=discord.Color.red(),
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        numero = numero_int
        _, role_id, prix, nom, *__ = items[numero - 1]
        role = interaction.guild.get_role(int(role_id))

        if role is None:
            embed = discord.Embed(
                title="❌ Rôle introuvable",
                description="Le rôle associé à cet article n’existe plus sur le serveur.",
                color=discord.Color.red(),
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if role in user.roles:
            embed = discord.Embed(
                title="⚠️ Rôle déjà possédé",
                description=f"{user.mention} a déjà {role.mention}.",
                color=discord.Color.orange(),
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if not deduire:
            try:
                await user.add_roles(role, reason=f"Article offert par {interaction.user}")
            except (discord.Forbidden, discord.HTTPException):
                await interaction.edit_original_response(
                    content="❌ Impossible d’attribuer ce rôle. Vérifie les permissions et la hiérarchie des rôles."
                )
                return
        else:
            config = await get_guild_economy_config(interaction.guild_id)
            db = await get_db_connection()
            role_added = False
            try:
                await db.begin()
                async with db.cursor() as cursor:
                    await cursor.execute(
                        "INSERT INTO guild_wallets (guild_id, user_id, balance) "
                        "VALUES (%s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)",
                        (interaction.guild_id, user.id, config["starting_balance"]),
                    )
                    await cursor.execute(
                        "SELECT balance FROM guild_wallets "
                        "WHERE guild_id = %s AND user_id = %s FOR UPDATE",
                        (interaction.guild_id, user.id),
                    )
                    balance = (await cursor.fetchone())[0]

                    if balance < prix:
                        await db.rollback()
                        embed = discord.Embed(
                            title="❌ Solde insuffisant",
                            description=(
                                f"{user.mention} a **{format_amount(balance)}💰** "
                                f"mais cet article coûte **{format_amount(prix)}💰**."
                            ),
                            color=discord.Color.red(),
                        )
                        set_bot_footer(embed, interaction)
                        await interaction.edit_original_response(embed=embed)
                        return

                    try:
                        await user.add_roles(
                            role, reason=f"Article avec débit donné par {interaction.user}"
                        )
                        role_added = True
                    except (discord.Forbidden, discord.HTTPException):
                        await db.rollback()
                        await interaction.edit_original_response(
                            content="❌ Impossible d’attribuer ce rôle. Aucun coin n’a été retiré."
                        )
                        return

                    await cursor.execute(
                        "UPDATE guild_wallets SET balance = balance - %s "
                        "WHERE guild_id = %s AND user_id = %s AND balance >= %s",
                        (prix, interaction.guild_id, user.id, prix),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError("The balance changed while assigning the role.")

                    await record_transaction(
                        db,
                        interaction.guild_id,
                        user.id,
                        "admin_giveitem",
                        -prix,
                        balance - prix,
                        detail=f"{nom} donné par {interaction.user}",
                    )
                await db.commit()
            except Exception as exc:
                await db.rollback()
                if role_added:
                    try:
                        await user.remove_roles(
                            role, reason="Annulation après échec de la transaction"
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                logging.getLogger(__name__).exception("Give-item failure for user=%s", user.id)
                await interaction.edit_original_response(
                    content="❌ L’attribution a échoué. Aucun coin n’a été retiré."
                )
                return
            finally:
                db.close()

        description = f"{user.mention} a reçu {role.mention} (**#{numero} — {nom}**)."
        if deduire:
            description += f"\n**{format_amount(prix)}💰** déduit de son solde."

        embed = discord.Embed(
            title="✅ Rôle attribué",
            description=description,
            color=discord.Color.green(),
        )
        set_bot_footer(embed, interaction)
        await interaction.edit_original_response(embed=embed)
