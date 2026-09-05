import discord
from discord import Interaction
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.format import format_amount


async def register(bot):
    @bot.tree.command(name="economystats", description="Statistiques économiques du serveur (Admin seulement)")
    async def economy_stats(interaction: Interaction):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(title="❌ Permission refusée", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer()

        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute("SELECT COUNT(*), SUM(balance), AVG(balance), MIN(balance), MAX(balance) FROM guild_wallets")
        total_users, total_supply, avg_balance, min_balance, max_balance = cursor.fetchone()
        total_supply = total_supply or 0
        avg_balance = avg_balance or 0

        cursor.execute("SELECT balance FROM guild_wallets ORDER BY balance")
        all_balances = [row[0] for row in cursor.fetchall()]
        n = len(all_balances)
        median = all_balances[n // 2] if n else 0

        cursor.execute("SELECT COUNT(*) FROM guild_wallets WHERE balance = 0")
        broke_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM guild_wallets WHERE balance BETWEEN 1 AND 999")
        tier1 = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM guild_wallets WHERE balance BETWEEN 1000 AND 9999")
        tier2 = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM guild_wallets WHERE balance BETWEEN 10000 AND 49999")
        tier3 = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM guild_wallets WHERE balance >= 50000")
        tier4 = cursor.fetchone()[0]

        cursor.execute("SELECT MIN(prix), MAX(prix), AVG(prix), COUNT(*) FROM guild_boutique_roles")
        shop_min, shop_max, shop_avg, shop_count = cursor.fetchone()

        cursor.execute("SELECT COUNT(*) FROM guild_wallets WHERE balance >= (SELECT MIN(prix) FROM guild_boutique_roles)")
        can_afford = cursor.fetchone()[0]

        cursor.close()
        db.close()

        active_users = total_users - broke_users

        embed = discord.Embed(
            title="📊 Statistiques économiques",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="💰 Circulation",
            value=(
                f"Total en circulation : **{format_amount(total_supply)}💰**\n"
                f"Moyenne : **{format_amount(int(avg_balance))}💰**\n"
                f"Médiane : **{format_amount(median)}💰**\n"
                f"Min : **{format_amount(min_balance)}💰** — Max : **{format_amount(max_balance)}💰**"
            ),
            inline=False
        )

        embed.add_field(
            name="👥 Utilisateurs",
            value=(
                f"Total : **{total_users}**\n"
                f"Actifs (solde > 0) : **{active_users}**\n"
                f"Vides (0💰) : **{broke_users}**"
            ),
            inline=False
        )

        embed.add_field(
            name="📈 Distribution des soldes",
            value=(
                f"0💰 : **{broke_users}** joueurs\n"
                f"1 – 999💰 : **{tier1}** joueurs\n"
                f"1K – 9.9K💰 : **{tier2}** joueurs\n"
                f"10K – 49.9K💰 : **{tier3}** joueurs\n"
                f"50K+💰 : **{tier4}** joueurs"
            ),
            inline=False
        )

        if shop_count:
            embed.add_field(
                name="🛍️ Boutique",
                value=(
                    f"Articles : **{shop_count}**\n"
                    f"Prix min : **{format_amount(shop_min)}💰** — Prix max : **{format_amount(shop_max)}💰**\n"
                    f"Prix moyen : **{format_amount(int(shop_avg))}💰**\n"
                    f"Joueurs pouvant acheter : **{can_afford}/{active_users}**"
                ),
                inline=False
            )

        set_bot_footer(embed, interaction)
        await interaction.followup.send(embed=embed)
