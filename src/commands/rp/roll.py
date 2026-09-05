import discord
from discord import Interaction, app_commands
from src.utils.dice import roll as dice_roll, get_help, ParseError
from src.utils.embed import set_bot_footer
from src.utils.error_reporting import report_error


async def register(bot):
    @bot.tree.command(name="roll", description="Lancer des dés — /roll help pour la syntaxe")
    @app_commands.describe(expression="Ex: 2d6+3 · 4d6 k3 · 6 4d6 · dndstats · wng 6")
    async def roll(interaction: Interaction, expression: str):
        if expression.strip().lower() in ("help", "aide"):
            embed = discord.Embed(
                title="🎲 Aide — Lancers de dés",
                description=get_help(),
                color=discord.Color.blurple()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        try:
            output, private = dice_roll(expression)
        except ParseError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return
        except Exception as exc:
            ref = await report_error(
                bot, guild_ids=interaction.guild_id, source="/roll", error=exc, user=interaction.user
            )
            await interaction.response.send_message(
                f"❌ Une erreur interne est survenue. Référence : `{ref}`", ephemeral=True
            )
            return

        embed = discord.Embed(description=output, color=discord.Color.blurple())
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=private)
