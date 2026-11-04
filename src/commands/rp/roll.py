import discord
from io import BytesIO
import re
from discord import Interaction, app_commands
from src.utils.dice import roll as dice_roll, get_help, ParseError, MAX_EXPRESSION_LENGTH
from src.utils.embed import set_bot_footer
from src.utils.error_reporting import report_error


def prepare_output(output: str) -> tuple[str, discord.File | None]:
    # UTF-16 counting also covers clients that count emoji as two code units.
    if len(output.encode("utf-16-le")) // 2 <= 4096:
        return output, None
    # Summarize the already rolled values; never reroll to produce the summary.
    summary = re.sub(r"`\[[^`\n]*\]`", "…", output)
    encoded = summary.encode("utf-16-le")
    if len(encoded) // 2 > 3500:
        summary = encoded[:7000].decode("utf-16-le", errors="ignore") + "\n… Suite dans le fichier joint."
    description = summary + "\n\n📎 Le détail complet des résultats est dans le fichier joint."
    file = discord.File(BytesIO(output.encode("utf-8")), filename="resultats-des.txt")
    return description, file


async def register(bot):
    @bot.tree.command(name="roll", description="Lancer des dés — /roll help pour la syntaxe")
    @app_commands.checks.cooldown(5, 10, key=lambda interaction: (interaction.guild_id, interaction.user.id))
    @app_commands.describe(expression="Ex: 2d6+3 · 4d6 k3 · 6 4d6 · dndstats · wng 6")
    async def roll(interaction: Interaction, expression: app_commands.Range[str, 1, MAX_EXPRESSION_LENGTH]):
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

        description, file = prepare_output(output)
        embed = discord.Embed(description=description, color=discord.Color.blurple())
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url
        )
        set_bot_footer(embed, interaction)
        try:
            if file is None:
                await interaction.response.send_message(
                    embed=embed, ephemeral=private, allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                await interaction.response.defer(ephemeral=private, thinking=True)
                await interaction.followup.send(
                    embed=embed, file=file, ephemeral=private, allowed_mentions=discord.AllowedMentions.none(),
                )
        finally:
            if file is not None:
                file.close()
                file.fp.close()
