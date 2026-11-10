"""Global application-command errors coordinated with local error handlers."""

from discord import app_commands

from src.utils.error_reporting import report_error

ERROR_HANDLED_KEY = "app_command_error_handled"


def command_source(interaction, *, fallback="inconnue"):
    command = interaction.command
    return f"/{command.qualified_name}" if command is not None else fallback


async def handle_app_command_error(bot, interaction, error):
    # discord.py invokes the tree handler even after a command/group error handler.
    if interaction.extras.get(ERROR_HANDLED_KEY):
        return
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"Patiente encore {max(1, int(error.retry_after) + 1)} secondes avant de réutiliser cette commande."
    elif isinstance(error, app_commands.CheckFailure):
        message = "❌ Vous n'avez pas la permission d'utiliser cette commande."
    else:
        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
        ref = await report_error(
            bot,
            guild_ids=interaction.guild_id,
            source=command_source(interaction),
            error=original,
            user=interaction.user,
        )
        message = f"❌ Une erreur est survenue pendant l'exécution de cette commande. Référence : `{ref}`"
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)
    interaction.extras[ERROR_HANDLED_KEY] = True
