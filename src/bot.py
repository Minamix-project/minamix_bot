import os
import asyncio
from dotenv import load_dotenv
import pymysql
import discord
from discord.ext import commands
from discord import app_commands

from src.config import GUILD_IDS
from src.core.db_init import init_db
from src.core.loader import load_modules
from src.utils.permissions import configure_command_permissions


def run_bot():
    asyncio.run(_main())


async def _main():
    load_dotenv()

    db = pymysql.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", 3306)),
        charset="utf8mb4",
        autocommit=True,
    )
    init_db(db)

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
            print(f"[ERREUR COMMANDE] {interaction.command}: {error}")
            message = "❌ Une erreur est survenue pendant l'exécution de cette commande."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def send_deployment_logs() -> None:
        if os.getenv("DEPLOY_NOTIFICATION") != "1":
            return
        for guild_id in GUILD_IDS:
            db = get_db_connection()
            try:
                with db.cursor() as cursor:
                    cursor.execute(
                        "SELECT value FROM guild_config WHERE guild_id = %s AND config_key = 'logs_channel'",
                        (guild_id,),
                    )
                    row = cursor.fetchone()
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

    await load_modules(bot, "src/events", "EVENT")
    await load_modules(bot, "src/commands", "CMD")
    configure_command_permissions(bot)

    try:
        await bot.start(token)
    except KeyboardInterrupt:
        await bot.close()


if __name__ == "__main__":
    run_bot()
