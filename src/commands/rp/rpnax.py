from src.utils.permissions import admin_only
import discord
from discord import Interaction, Member, app_commands
from discord.ui import Select
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.views import ExpiringView

NAX_EMOJI = "<:nax:1508570111437574254>"


async def register(bot):

    @bot.tree.command(name="addnax", description="Ajouter des Nax à un personnage (Admin)")
    @app_commands.describe(user="Propriétaire du personnage", montant="Montant à ajouter")
    @admin_only()
    async def addnax(interaction: Interaction, user: Member, montant: int):
        if montant <= 0:
            await interaction.response.send_message("❌ Le montant doit être positif.", ephemeral=True)
            return

        await _pick_character(interaction, user, montant, action="add")

    @bot.tree.command(name="removenax", description="Retirer des Nax à un personnage (Admin)")
    @app_commands.describe(user="Propriétaire du personnage", montant="Montant à retirer")
    @admin_only()
    async def removenax(interaction: Interaction, user: Member, montant: int):
        if montant <= 0:
            await interaction.response.send_message("❌ Le montant doit être positif.", ephemeral=True)
            return

        await _pick_character(interaction, user, montant, action="remove")


async def _pick_character(interaction: Interaction, user: Member, montant: int, action: str):
    db = await get_db_connection()
    cursor = await db.cursor()
    await cursor.execute(
        "SELECT id, name, nax_balance FROM rp_characters "
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

    if len(rows) == 1:
        char_id, char_name, _balance = rows[0]
        await _apply(interaction, user, char_id, char_name, montant, action)
        return

    options = [
        discord.SelectOption(
            label=name,
            value=str(char_id),
            description=f"{balance:,} {NAX_EMOJI} actuellement".replace(",", " ")
        )
        for char_id, name, balance in rows
    ]
    select = Select(placeholder="Choisir un personnage...", options=options)

    async def on_select(inter: Interaction):
        char_id = int(select.values[0])
        char = next((r for r in rows if r[0] == char_id), None)
        if not char:
            await inter.response.send_message("❌ Personnage introuvable.", ephemeral=True)
            return
        _, char_name, _balance = char
        await _apply(inter, user, char_id, char_name, montant, action)

    select.callback = on_select
    view = ExpiringView(owner_id=interaction.user.id)
    view.add_item(select)

    verb = "Ajouter à" if action == "add" else "Retirer à"
    embed = discord.Embed(
        title=f"🎭 {verb} {user.display_name}",
        description=f"Sélectionne le personnage.",
        color=discord.Color.blurple()
    )
    set_bot_footer(embed, interaction)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    view.message = await interaction.original_response()


async def _apply(interaction: Interaction, user: Member, char_id: int, char_name: str, montant: int, action: str):
    delta = montant if action == "add" else -montant
    db = await get_db_connection()
    try:
        await db.begin()
        async with db.cursor() as cursor:
            await cursor.execute(
                "UPDATE rp_characters SET nax_balance = nax_balance + %s "
                "WHERE id = %s AND guild_id = %s AND user_id = %s "
                "AND nax_balance + %s >= 0",
                (delta, char_id, interaction.guild_id, user.id, delta),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                embed = discord.Embed(
                    title="❌ Opération impossible",
                    description="Le personnage n'existe plus ou son solde est insuffisant.",
                    color=discord.Color.red(),
                )
                set_bot_footer(embed, interaction)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            await cursor.execute(
                "SELECT nax_balance FROM rp_characters WHERE id = %s AND guild_id = %s",
                (char_id, interaction.guild_id),
            )
            new_balance = (await cursor.fetchone())[0]
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        db.close()

    formatted = f"{montant:,}".replace(",", " ")
    new_fmt = f"{new_balance:,}".replace(",", " ")

    if action == "add":
        desc = f"**+{formatted} {NAX_EMOJI}** ajoutés à **{char_name}** ({user.mention})\nNouveau solde : **{new_fmt} {NAX_EMOJI}**"
        color = discord.Color.green()
        title = "✅ Nax ajoutés"
    else:
        desc = f"**-{formatted} {NAX_EMOJI}** retirés à **{char_name}** ({user.mention})\nNouveau solde : **{new_fmt} {NAX_EMOJI}**"
        color = discord.Color.orange()
        title = "✅ Nax retirés"

    embed = discord.Embed(title=title, description=desc, color=color)
    set_bot_footer(embed, interaction)
    await interaction.response.send_message(embed=embed, ephemeral=True)
