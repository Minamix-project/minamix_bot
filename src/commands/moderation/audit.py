from src.utils.permissions import admin_only
from discord import Interaction, Member, Embed, app_commands
import discord
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.pagination import PaginationView
from src.utils.permissions import ADMIN_COMMANDS, RP_MANAGER_COMMANDS

PAGE_SIZE = 10
_ALL_COMMANDS = sorted(ADMIN_COMMANDS | RP_MANAGER_COMMANDS)


async def _commande_autocomplete(interaction: Interaction, current: str):
    current = (current or "").lower()
    matches = [name for name in _ALL_COMMANDS if current in name.lower()]
    return [app_commands.Choice(name=name, value=name) for name in matches[:25]]


async def register(bot):
    @bot.tree.command(name="audit", description="Voir les dernières actions administratives (Admin seulement)")
    @app_commands.describe(
        auteur="Filtrer par membre ayant exécuté l'action",
        commande="Filtrer par commande",
        depuis_jours="Ne montrer que les N derniers jours",
    )
    @app_commands.autocomplete(commande=_commande_autocomplete)
    @admin_only()
    async def audit(interaction: Interaction, auteur: Member = None, commande: str = None, depuis_jours: int = None):
        conditions = ["guild_id = %s"]
        params = [interaction.guild_id]
        if auteur is not None:
            conditions.append("actor_id = %s")
            params.append(auteur.id)
        if commande is not None:
            conditions.append("action = %s")
            params.append(commande)
        if depuis_jours is not None:
            conditions.append("created_at >= NOW() - INTERVAL %s DAY")
            params.append(depuis_jours)

        db = await get_db_connection()
        try:
            async with db.cursor() as cursor:
                await cursor.execute(
                    f"SELECT actor_id, action, created_at FROM admin_audit WHERE {' AND '.join(conditions)} "
                    "ORDER BY created_at DESC LIMIT 500",
                    params,
                )
                rows = await cursor.fetchall()
        finally:
            db.close()

        filters_desc = []
        if auteur is not None:
            filters_desc.append(f"auteur={auteur.mention}")
        if commande is not None:
            filters_desc.append(f"commande=`/{commande}`")
        if depuis_jours is not None:
            filters_desc.append(f"depuis {depuis_jours}j")
        filters_text = " · ".join(filters_desc) if filters_desc else "Aucun filtre"

        if not rows:
            embed = discord.Embed(
                title="📋 Journal d'audit",
                description=f"*{filters_text}*\n\nAucune action trouvée.",
                color=discord.Color.orange(),
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        total_pages = (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE

        def render_page(page: int) -> Embed:
            start = (page - 1) * PAGE_SIZE
            chunk = rows[start:start + PAGE_SIZE]
            lines = [
                f"<t:{int(created_at.timestamp())}:f> · <@{actor_id}> · `/{action}`"
                for actor_id, action, created_at in chunk
            ]
            embed = Embed(
                title="📋 Journal d'audit",
                description=f"*{filters_text}*\n\n" + "\n".join(lines),
                color=discord.Color.blurple(),
            )
            set_bot_footer(embed, interaction)
            return embed

        view = PaginationView(interaction.user.id, total_pages, render_page)
        await interaction.response.send_message(embed=view.current_embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()
