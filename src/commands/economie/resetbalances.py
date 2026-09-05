import discord
from discord import Interaction
from discord.ui import Button
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.views import ExpiringView
from src.utils.transactions import record_transaction
from src.utils.format import format_amount


class _ConfirmModal(discord.ui.Modal, title="Confirmation requise"):
    answer = discord.ui.TextInput(
        label='Tapez exactement : je suis sur',
        placeholder="je suis sur",
        required=True,
        max_length=30,
    )

    def __init__(self):
        super().__init__()
        self._interaction_callback = None

    async def on_submit(self, interaction: Interaction):
        if self.answer.value.strip().lower() != "je suis sur":
            embed = discord.Embed(
                title="❌ Texte incorrect",
                description=f'Tu as tapé `{self.answer.value}` — il fallait écrire exactement `je suis sur`.',
                color=discord.Color.red(),
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM guild_wallets WHERE guild_id = %s AND balance > 0",
            (interaction.guild_id,),
        )
        affected_count, affected_total = await cursor.fetchone()
        await cursor.close()
        db.close()

        embed = discord.Embed(
            title="🚨 Dernière chance",
            description=(
                f"Tu es sur le point de **remettre à zéro le solde de {affected_count} membre(s)**, "
                f"représentant **{format_amount(affected_total)}💰** au total.\n\n"
                "Cette action est **irréversible**."
            ),
            color=discord.Color.dark_red(),
        )
        set_bot_footer(embed, interaction)

        view = ExpiringView(timeout=30)
        yes_btn = Button(label="Oui, reset tout", style=discord.ButtonStyle.red, emoji="🚨")
        no_btn = Button(label="Non", style=discord.ButtonStyle.grey, emoji="❌")

        async def yes_callback(inter: Interaction):
            db = await get_db_connection()
            try:
                await db.begin()
                async with db.cursor() as cursor:
                    await cursor.execute(
                        "SELECT user_id, balance FROM guild_wallets WHERE guild_id = %s AND balance > 0 FOR UPDATE",
                        (inter.guild_id,),
                    )
                    rows = await cursor.fetchall()
                    for user_id, balance in rows:
                        await record_transaction(
                            db, inter.guild_id, user_id, "reset_admin",
                            -balance, 0, detail=f"Reset global par {inter.user}",
                        )
                    await cursor.execute("UPDATE guild_wallets SET balance = 0 WHERE guild_id = %s", (inter.guild_id,))
                    count = cursor.rowcount
                    await cursor.execute("UPDATE guild_work_cooldowns SET last_work = 0 WHERE guild_id = %s", (inter.guild_id,))
                await db.commit()
            except Exception:
                await db.rollback()
                raise
            finally:
                db.close()

            result_embed = discord.Embed(
                title="✅ Reset effectué",
                description=f"Les soldes de **{count}** membre(s) ont été remis à zéro.",
                color=discord.Color.green(),
            )
            set_bot_footer(result_embed, inter)
            await inter.response.edit_message(embed=result_embed, view=None)

        async def no_callback(inter: Interaction):
            cancel_embed = discord.Embed(title="❌ Reset annulé", color=discord.Color.red())
            set_bot_footer(cancel_embed, inter)
            await inter.response.edit_message(embed=cancel_embed, view=None)

        yes_btn.callback = yes_callback
        no_btn.callback = no_callback
        view.add_item(yes_btn)
        view.add_item(no_btn)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def register(bot):
    @bot.tree.command(name="resetbalances", description="Remettre à zéro tous les soldes (Admin seulement)")
    async def resetbalances(interaction: Interaction):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Permission refusée",
                description="Vous n'avez pas la permission d'utiliser cette commande.",
                color=discord.Color.red(),
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="⚠️ Réinitialisation des soldes",
            description=(
                "Tu t'apprêtes à **remettre à zéro le solde de tous les membres**.\n\n"
                "Cette action est **irréversible**. Es-tu sûr de vouloir continuer ?"
            ),
            color=discord.Color.orange(),
        )
        set_bot_footer(embed, interaction)

        view = ExpiringView(timeout=30)
        continue_btn = Button(label="Continuer", style=discord.ButtonStyle.danger, emoji="⚠️")
        cancel_btn = Button(label="Annuler", style=discord.ButtonStyle.grey, emoji="❌")

        async def continue_callback(inter: Interaction):
            await inter.response.send_modal(_ConfirmModal())

        async def cancel_callback(inter: Interaction):
            cancel_embed = discord.Embed(title="❌ Reset annulé", color=discord.Color.red())
            set_bot_footer(cancel_embed, inter)
            await inter.response.edit_message(embed=cancel_embed, view=None)

        continue_btn.callback = continue_callback
        cancel_btn.callback = cancel_callback
        view.add_item(continue_btn)
        view.add_item(cancel_btn)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()
