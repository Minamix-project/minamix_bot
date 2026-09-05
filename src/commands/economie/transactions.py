from discord import Interaction, Member, Embed, app_commands
import discord
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.format import format_amount
from src.utils.pagination import PaginationView

PAGE_SIZE = 10

_TYPE_LABELS = {
    "work": "💼 Travail",
    "message": "💬 Message",
    "achat": "🛒 Achat",
    "admin_add": "➕ Ajout admin",
    "admin_remove": "➖ Retrait admin",
    "admin_giveitem": "🎁 Article offert",
    "reset_admin": "🚨 Reset admin",
}


async def register(bot):
    @bot.tree.command(name="transactions", description="Voir l'historique économique d'un utilisateur.")
    @app_commands.describe(user="Utilisateur (toi par défaut, admin requis pour un autre membre)")
    async def transactions(interaction: Interaction, user: Member = None):
        target = user or interaction.user
        if user is not None and user.id != interaction.user.id and not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Permission refusée",
                description="Seul un administrateur peut consulter l'historique d'un autre membre.",
                color=discord.Color.red(),
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        db = await get_db_connection()
        try:
            async with db.cursor() as cursor:
                await cursor.execute(
                    "SELECT type, amount, balance_after, detail, created_at FROM guild_transactions "
                    "WHERE guild_id = %s AND user_id = %s ORDER BY created_at DESC",
                    (interaction.guild_id, target.id),
                )
                rows = await cursor.fetchall()
        finally:
            db.close()

        if not rows:
            embed = discord.Embed(
                title=f"📜 Historique de {target.display_name}",
                description="Aucune transaction enregistrée.",
                color=discord.Color.orange(),
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        total_pages = (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE

        def render_page(page: int) -> Embed:
            start = (page - 1) * PAGE_SIZE
            chunk = rows[start:start + PAGE_SIZE]
            lines = []
            for type_, amount, balance_after, detail, created_at in chunk:
                label = _TYPE_LABELS.get(type_, type_)
                sign = "+" if amount >= 0 else ""
                line = f"<t:{int(created_at.timestamp())}:d> · {label} · **{sign}{format_amount(amount)}💰** (solde : {format_amount(balance_after)}💰)"
                if detail:
                    line += f"\n> {detail}"
                lines.append(line)
            embed = Embed(
                title=f"📜 Historique de {target.display_name}",
                description="\n".join(lines),
                color=discord.Color.blurple(),
            )
            set_bot_footer(embed, interaction)
            return embed

        view = PaginationView(interaction.user.id, total_pages, render_page)
        await interaction.response.send_message(embed=view.current_embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()
