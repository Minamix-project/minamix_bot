"""Purchase flow shared between /buy and the "Buy" buttons on /shop."""

from discord import Embed, Interaction
from discord.ui import Button
import discord

from src.utils.db import get_db_connection
from src.utils.format import format_amount
from src.utils.embed import set_bot_footer
from src.utils.views import ExpiringView
from src.utils.transactions import record_transaction


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
        print(f"[LOG ACHAT] Envoi ignoré : {exc}")
    except Exception as exc:
        print(f"[LOG ACHAT] Lecture de configuration impossible : {exc}")


async def process_purchase(interaction: Interaction, role_id: int, prix: int, nom_role: str):
    await interaction.response.defer()

    role = interaction.guild.get_role(int(role_id))
    if role is None:
        await interaction.edit_original_response(content="❌ Le rôle associé à cet article n'existe plus.", view=None)
        return
    if role in interaction.user.roles:
        await interaction.edit_original_response(content=f"❌ Tu possèdes déjà {role.mention}.", view=None)
        return

    from src.utils.economy_config import get_guild_economy_config
    starting_balance = (await get_guild_economy_config(interaction.guild_id))["starting_balance"]

    db = await get_db_connection()
    role_added = False
    try:
        await db.begin()
        async with db.cursor() as cursor:
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
        if role_added:
            try:
                await interaction.user.remove_roles(role, reason="Annulation d'un achat boutique échoué")
            except (discord.Forbidden, discord.HTTPException):
                pass
        print(f"[ACHAT] Échec pour {interaction.user.id}: {exc}")
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


async def show_purchase_confirmation(interaction: Interaction, role_id: int, prix: int, nom_role: str, edit: bool = False):
    embed = Embed(
        title="🛒 Confirmer l'achat ?",
        description=f"Tu t'apprêtes à acheter <@&{role_id}> pour **{format_amount(prix)}💰**.",
        color=discord.Color.blurple()
    )
    set_bot_footer(embed, interaction)

    view = ExpiringView(timeout=30)

    confirm_btn = Button(label="Confirmer", style=discord.ButtonStyle.green, emoji="✅")
    cancel_btn = Button(label="Annuler", style=discord.ButtonStyle.red, emoji="❌")

    async def confirm_callback(inter: Interaction):
        await process_purchase(inter, role_id, prix, nom_role)

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
