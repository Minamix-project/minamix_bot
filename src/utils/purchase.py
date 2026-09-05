"""Purchase flow shared between /buy and the "Buy" buttons on /shop."""

from discord import Embed, Interaction
from discord.ui import Button
import discord
import logging

from src.utils.db import get_db_connection
from src.utils.format import format_amount
from src.utils.embed import set_bot_footer
from src.utils.views import ExpiringView
from src.utils.transactions import record_transaction

logger = logging.getLogger(__name__)


async def send_purchase_log(interaction, role, prix, success: bool, detail: str):
    try:
        db = await get_db_connection()
        try:
            async with db.cursor() as cursor:
                await cursor.execute(
                    "SELECT value FROM guild_config WHERE guild_id = %s AND config_key = %s",
                    (interaction.guild_id, "logs_channel"),
                )
                row = await cursor.fetchone()
        finally:
            db.close()

        if not row:
            return
        channel = interaction.guild.get_channel(int(row[0]))
        if channel is None:
            return

        embed = Embed(
            title="🛒 Achat réussi" if success else "❌ Échec d’achat",
            color=discord.Color.green() if success else discord.Color.red(),
        )
        embed.add_field(name="Utilisateur", value=interaction.user.mention)
        embed.add_field(name="Rôle", value=role.mention if role else "Introuvable")
        embed.add_field(name="Prix", value=f"{format_amount(prix)}💰")
        embed.add_field(name="Détail", value=detail, inline=False)
        await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException, ValueError, TypeError) as exc:
        logger.warning("Envoi du log d'achat ignoré : %s", exc)
    except Exception as exc:
        logger.exception("Lecture de la configuration du log d'achat impossible")


async def process_purchase(interaction: Interaction, item_id: int, expected_price: int):
    await interaction.response.defer()

    db = await get_db_connection()
    role_added = False
    role = None
    prix = expected_price
    nom_role = "article"
    try:
        await db.begin()
        async with db.cursor() as cursor:
            await cursor.execute(
                "SELECT role_id, prix, nom FROM guild_boutique_roles "
                "WHERE guild_id = %s AND id = %s FOR UPDATE",
                (interaction.guild_id, item_id),
            )
            item = await cursor.fetchone()
            if item is None:
                await db.rollback()
                await interaction.edit_original_response(
                    content="❌ Cet article n'est plus disponible. Recharge la boutique.", view=None
                )
                return
            role_id, prix, nom_role = item
            if prix != expected_price:
                await db.rollback()
                await interaction.edit_original_response(
                    content="⚠️ Le prix de cet article a changé. Recharge la boutique avant de confirmer.", view=None
                )
                return

            role = interaction.guild.get_role(int(role_id))
            if role is None:
                await db.rollback()
                await interaction.edit_original_response(
                    content="❌ Le rôle associé à cet article n'existe plus.", view=None
                )
                return
            if role in interaction.user.roles:
                await db.rollback()
                await interaction.edit_original_response(
                    content=f"❌ Tu possèdes déjà {role.mention}.", view=None
                )
                return

            from src.utils.economy_config import get_guild_economy_config
            starting_balance = (await get_guild_economy_config(interaction.guild_id))["starting_balance"]
            await cursor.execute(
                "INSERT INTO guild_wallets (guild_id, user_id, balance) VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)",
                (interaction.guild_id, interaction.user.id, starting_balance),
            )
            await cursor.execute("SELECT balance FROM guild_wallets WHERE guild_id = %s AND user_id = %s FOR UPDATE", (interaction.guild_id, interaction.user.id))
            current_balance = (await cursor.fetchone())[0]

            if current_balance < prix:
                await db.rollback()
                embed = Embed(
                    title="❌ Solde insuffisant",
                    description=f"Tu as **{format_amount(current_balance)}💰** mais cet article coûte **{format_amount(prix)}💰**.",
                    color=discord.Color.red(),
                )
                set_bot_footer(embed, interaction)
                await interaction.edit_original_response(embed=embed, view=None)
                return

            try:
                await interaction.user.add_roles(role, reason=f"Achat boutique : {nom_role}")
                role_added = True
            except (discord.Forbidden, discord.HTTPException):
                await db.rollback()
                await interaction.edit_original_response(
                    content="❌ Impossible d'attribuer ce rôle. Aucun coin n'a été retiré.", view=None
                )
                await send_purchase_log(interaction, role, prix, False, "Attribution Discord refusée; aucun débit.")
                return

            await cursor.execute(
                "UPDATE guild_wallets SET balance = balance - %s WHERE guild_id = %s AND user_id = %s AND balance >= %s",
                (prix, interaction.guild_id, interaction.user.id, prix),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Le solde a changé pendant l'achat.")
            await record_transaction(
                db, interaction.guild_id, interaction.user.id, "achat",
                -prix, current_balance - prix, detail=nom_role,
            )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        if role_added and role is not None:
            try:
                await interaction.user.remove_roles(role, reason="Annulation d'un achat boutique échoué")
            except (discord.Forbidden, discord.HTTPException) as compensation_exc:
                logger.critical(
                    "Compensation Discord impossible après échec d'achat user=%s role=%s: %s",
                    interaction.user.id, role.id, compensation_exc,
                )
                await send_purchase_log(
                    interaction, role, prix, False,
                    "Le débit a été annulé mais le rôle n'a pas pu être retiré; intervention manuelle requise.",
                )
        logger.exception("Échec de l'achat pour user=%s", interaction.user.id)
        await interaction.edit_original_response(
            content="❌ L'achat a échoué. Aucun coin n'a été retiré.", view=None
        )
        return
    finally:
        db.close()

    embed = Embed(
        title="✅ Achat réussi !",
        description=f"Tu as acheté {role.mention} pour **{format_amount(prix)}💰**.",
        color=discord.Color.green(),
    )
    set_bot_footer(embed, interaction)
    await interaction.edit_original_response(embed=embed, view=None)
    await send_purchase_log(interaction, role, prix, True, "Rôle attribué et solde débité.")


async def show_purchase_confirmation(
    interaction: Interaction, item_id: int, role_id: int, prix: int,
    nom_role: str, edit: bool = False,
):
    embed = Embed(
        title="🛒 Confirmer l'achat ?",
        description=f"Tu t'apprêtes à acheter <@&{role_id}> pour **{format_amount(prix)}💰**.",
        color=discord.Color.blurple()
    )
    set_bot_footer(embed, interaction)

    view = ExpiringView(timeout=30, owner_id=interaction.user.id)

    confirm_btn = Button(label="Confirmer", style=discord.ButtonStyle.green, emoji="✅")
    cancel_btn = Button(label="Annuler", style=discord.ButtonStyle.red, emoji="❌")

    async def confirm_callback(inter: Interaction):
        await process_purchase(inter, item_id, prix)

    async def cancel_callback(inter: Interaction):
        cancel_embed = Embed(title="❌ Achat annulé", color=discord.Color.red())
        set_bot_footer(cancel_embed, inter)
        await inter.response.edit_message(embed=cancel_embed, view=None)

    confirm_btn.callback = confirm_callback
    cancel_btn.callback = cancel_callback
    view.add_item(confirm_btn)
    view.add_item(cancel_btn)

    if edit:
        await interaction.response.edit_message(embed=embed, view=view)
    else:
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    view.message = await interaction.original_response()
