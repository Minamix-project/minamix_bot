from src.utils.permissions import admin_only
import discord
from discord import Interaction
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.format import format_amount


async def register(bot):
    @bot.tree.command(name="economystats", description="Statistiques économiques du serveur (Admin seulement)")
    @admin_only()
    async def economy_stats(interaction: Interaction):
        await interaction.response.defer()

        db = await get_db_connection()
        cursor = await db.cursor()

        await cursor.execute("SELECT COUNT(*), SUM(balance), AVG(balance), MIN(balance), MAX(balance) FROM guild_wallets WHERE guild_id = %s", (interaction.guild_id,))
        total_users, total_supply, avg_balance, min_balance, max_balance = (await cursor.fetchone())
        total_supply = total_supply or 0
        avg_balance = avg_balance or 0

        await cursor.execute("SELECT balance FROM guild_wallets WHERE guild_id = %s ORDER BY balance", (interaction.guild_id,))
        all_balances = [row[0] for row in (await cursor.fetchall())]
        n = len(all_balances)
        median = all_balances[n // 2] if n else 0

        await cursor.execute("SELECT COUNT(*) FROM guild_wallets WHERE guild_id = %s AND balance = 0", (interaction.guild_id,))
        broke_users = (await cursor.fetchone())[0]

        await cursor.execute("SELECT COUNT(*) FROM guild_wallets WHERE guild_id = %s AND balance BETWEEN 1 AND 999", (interaction.guild_id,))
        tier1 = (await cursor.fetchone())[0]
        await cursor.execute("SELECT COUNT(*) FROM guild_wallets WHERE guild_id = %s AND balance BETWEEN 1000 AND 9999", (interaction.guild_id,))
        tier2 = (await cursor.fetchone())[0]
        await cursor.execute("SELECT COUNT(*) FROM guild_wallets WHERE guild_id = %s AND balance BETWEEN 10000 AND 49999", (interaction.guild_id,))
        tier3 = (await cursor.fetchone())[0]
        await cursor.execute("SELECT COUNT(*) FROM guild_wallets WHERE guild_id = %s AND balance >= 50000", (interaction.guild_id,))
        tier4 = (await cursor.fetchone())[0]

        await cursor.execute("SELECT MIN(prix), MAX(prix), AVG(prix), COUNT(*) FROM guild_boutique_roles WHERE guild_id = %s", (interaction.guild_id,))
        shop_min, shop_max, shop_avg, shop_count = (await cursor.fetchone())

        await cursor.execute("SELECT COUNT(*) FROM guild_wallets WHERE guild_id = %s AND balance >= (SELECT MIN(prix) FROM guild_boutique_roles WHERE guild_id = %s)", (interaction.guild_id, interaction.guild_id))
        can_afford = (await cursor.fetchone())[0]

        await cursor.close()
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
