import discord
from discord import Interaction, Member, app_commands
from discord.ui import Select
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.views import ExpiringView

NAX_ICON = "src/assets/nax.png"
# Remplace par l'emoji serveur une fois uploadé : "<:nax:ID_EMOJI>"
NAX_EMOJI = "<:nax:1508570111437574254>"


def _build_embed(char_name: str, balance: int, owner: discord.Member) -> discord.Embed:
    formatted = f"{balance:,}".replace(",", " ")
    embed = discord.Embed(
        title=f"Bourse de {char_name}",
        description=f"**{formatted} {NAX_EMOJI}**",
        color=discord.Color.from_rgb(230, 180, 150),
    )
    embed.set_footer(text=f"Personnage de {owner.display_name}")
    return embed


async def register(bot):
    @bot.tree.command(name="rpbourse", description="Voir la bourse Nax d'un personnage RP")
    @app_commands.describe(user="Utilisateur (laisse vide pour toi-même)")
    async def rpbourse(interaction: Interaction, user: Member = None):
        target = user or interaction.user

        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT id, name, nax_balance FROM rp_characters "
            "WHERE guild_id = %s AND user_id = %s ORDER BY created_at ASC",
            (interaction.guild.id, target.id)
        )
        rows = (await cursor.fetchall())
        await cursor.close()
        db.close()

        if not rows:
            await interaction.response.send_message(
                f"**{target.display_name}** n'a aucun personnage sur ce serveur.",
                ephemeral=True
            )
            return

        # Single character: show directly
        if len(rows) == 1:
            char_id, char_name, balance = rows[0]
            embed = _build_embed(char_name, balance, target)
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed)
            return

        # Multiple characters: dropdown
        options = [
            discord.SelectOption(label=name, value=str(char_id))
            for char_id, name, _ in rows
        ]
        select = Select(placeholder="Choisir un personnage...", options=options)

        async def on_select(inter: Interaction):
            char_id = int(select.values[0])
            char = next((r for r in rows if r[0] == char_id), None)
            if not char:
                await inter.response.send_message("❌ Personnage introuvable.", ephemeral=True)
                return

            _, char_name, balance = char
            embed = _build_embed(char_name, balance, target)
            set_bot_footer(embed, inter)
            await inter.response.send_message(embed=embed)

        select.callback = on_select
        view = ExpiringView()
        view.add_item(select)

        embed = discord.Embed(
            title=f"🎭 Personnages de {target.display_name}",
            description="Sélectionne un personnage pour voir sa bourse.",
            color=discord.Color.blurple()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()
