import os
import asyncio
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
import discord
from discord.ext import commands, tasks
from discord import app_commands

load_dotenv()

from src.config import GUILD_IDS
from src.core.db_init import init_db
from src.core.loader import load_modules
from src.utils.db import close_db_pool, create_db_pool, get_db_connection
from src.utils.permissions import ADMIN_COMMANDS
from src.utils.audit import record_admin_action
from src.utils.error_reporting import report_error


def run_bot():
    asyncio.run(_main())


async def _main():
    log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    await create_db_pool()
    db = await get_db_connection()
    try:
        await init_db(db)
    finally:
        db.close()

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN manquant dans le .env")

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    async def guild_only(interaction: discord.Interaction) -> bool:
        if interaction.guild_id not in GUILD_IDS:
            await interaction.response.send_message(
                "❌ Ce bot n'est pas disponible sur ce serveur.", ephemeral=True
            )
            return False
        return True


    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            message = "❌ Vous n'avez pas la permission d'utiliser cette commande."
        else:
            command_name = interaction.command.name if interaction.command else "inconnue"
            ref = await report_error(
                bot, guild_ids=interaction.guild_id, source=f"/{command_name}",
                error=error, user=interaction.user,
            )
            message = f"❌ Une erreur est survenue pendant l'exécution de cette commande. Référence : `{ref}`"

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @bot.event
    async def on_error(event_method, *args, **kwargs):
        import sys
        error = sys.exc_info()[1]
        guild_id = next((getattr(getattr(a, "guild", None), "id", None) for a in args if getattr(a, "guild", None)), None)
        await report_error(bot, guild_ids=guild_id if guild_id is not None else GUILD_IDS, source=f"event:{event_method}", error=error)

    async def send_deployment_logs() -> None:
        if os.getenv("DEPLOY_NOTIFICATION") != "1":
            return
        for guild_id in GUILD_IDS:
            db = await get_db_connection()
            try:
                async with db.cursor() as cursor:
                    await cursor.execute(
                        "SELECT value FROM guild_config WHERE guild_id = %s AND config_key = 'logs_channel'",
                        (guild_id,),
                    )
                    row = (await cursor.fetchone())
            finally:
                db.close()
            if not row:
                continue
            channel = bot.get_channel(int(row[0]))
            if channel is None:
                continue
            embed = discord.Embed(title="🚀 Déploiement du bot", color=discord.Color.green())
            embed.add_field(name="Version", value=os.getenv("BOT_VERSION", "dev"), inline=True)
            embed.add_field(name="Commit", value=os.getenv("GIT_COMMIT", "inconnu"), inline=True)
            await channel.send(embed=embed)

    bot.tree.interaction_check = guild_only

    _last_notified_backup_test = {"tested_at": None}
    backup_test_status_file = Path("backup_test_status/last_restore_test.json")

    @tasks.loop(hours=1)
    async def check_backup_test_status():
        if not backup_test_status_file.exists():
            return
        try:
            status = json.loads(backup_test_status_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        if status.get("status") != "fail":
            return
        if status.get("tested_at") == _last_notified_backup_test["tested_at"]:
            return
        _last_notified_backup_test["tested_at"] = status.get("tested_at")

        for guild_id in GUILD_IDS:
            db = await get_db_connection()
            try:
                async with db.cursor() as cursor:
                    await cursor.execute(
                        "SELECT value FROM guild_config WHERE guild_id = %s AND config_key = 'error_logs_channel'",
                        (guild_id,),
                    )
                    row = await cursor.fetchone()
            finally:
                db.close()
            if not row:
                continue
            channel = bot.get_channel(int(row[0]))
            if channel is None:
                continue
            embed = discord.Embed(
                title="🚨 Test de restauration de sauvegarde échoué",
                description=f"Fichier : `{status.get('file') or '—'}`\n{status.get('detail', '')}",
                color=discord.Color.red(),
            )
            try:
                await channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

    @bot.event
    async def on_app_command_completion(interaction, command):
        if command.name in ADMIN_COMMANDS and interaction.guild_id:
            try:
                await record_admin_action(interaction.guild_id, interaction.user.id, command.name)
            except Exception as exc:
                print(f"[AUDIT] {exc}")

    @bot.event
    async def on_message(message: discord.Message):
        if message.guild is None or message.guild.id not in GUILD_IDS:
            return
        await bot.process_commands(message)

    @bot.event
    async def on_ready():
        print(f"Connecté : {bot.user}")
        try:
            for guild_id in GUILD_IDS:
                guild = discord.Object(id=guild_id)
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
                print(f"[SYNC] {len(synced)} commandes → {guild_id}")
            bot.tree.clear_commands(guild=None)
            await bot.tree.sync()
            await send_deployment_logs()
        except Exception as e:
            print(f"[ERREUR SYNC] {e}")

        if not check_backup_test_status.is_running():
            check_backup_test_status.start()

    await load_modules(bot, "src/events", "EVENT")
    await load_modules(bot, "src/commands", "CMD")

    try:
        await bot.start(token)
    except KeyboardInterrupt:
        await bot.close()
    finally:
        await close_db_pool()


if __name__ == "__main__":
    run_bot()
