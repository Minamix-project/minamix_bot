"""Archive (without deleting) the old global tables wallets/users/boutique_roles.

These tables were replaced by the guild_* tables (see src/core/db_init.py,
_migrate_economy_per_guild) and are no longer used by the bot. This command
never does a DROP: it renames the tables (RENAME TABLE), which preserves
all the data and stays reversible if needed.
"""

from datetime import datetime, timezone

import discord
from discord import Interaction
from discord.ui import Button

from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.views import ExpiringView

LEGACY_TABLES = ["wallets", "users", "boutique_roles"]


class _ConfirmModal(discord.ui.Modal, title="Confirmation requise"):
    answer = discord.ui.TextInput(
        label="Tapez exactement : archiver ces tables",
        placeholder="archiver ces tables",
        required=True,
        max_length=40,
    )

    async def on_submit(self, interaction: Interaction):
        if self.answer.value.strip().lower() != "archiver ces tables":
            embed = discord.Embed(
                title="❌ Texte incorrect",
                description=f'Tu as tapé `{self.answer.value}` — il fallait écrire exactement `archiver ces tables`.',
                color=discord.Color.red(),
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        suffix = datetime.now(timezone.utc).strftime("%Y%m%d")
        db = await get_db_connection()
        cursor = await db.cursor()
        renamed = []
        try:
            for table in LEGACY_TABLES:
                await cursor.execute(
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                    (table,),
                )
                if (await cursor.fetchone())[0] == 0:
                    continue
                new_name = f"archived_{table}_{suffix}"
                await cursor.execute(f"RENAME TABLE `{table}` TO `{new_name}`")
                renamed.append(f"`{table}` → `{new_name}`")
            await db.commit()
        finally:
            await cursor.close()
            db.close()

        if not renamed:
            embed = discord.Embed(
                title="⚠️ Rien à archiver",
                description="Aucune des tables legacy n'existe encore (déjà archivées ?).",
                color=discord.Color.orange(),
            )
        else:
            embed = discord.Embed(
                title="✅ Tables archivées",
                description=(
                    "Les tables suivantes ont été renommées (aucune donnée supprimée) :\n"
                    + "\n".join(renamed)
                ),
                color=discord.Color.green(),
            )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def register(bot):
    @bot.tree.command(
        name="archivelegacytables",
        description="Archiver les anciennes tables globales wallets/users/boutique_roles (Admin seulement)",
    )
    async def archivelegacytables(interaction: Interaction):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(title="❌ Permission refusée", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="⚠️ Archiver les tables legacy ?",
            description=(
                "Tu t'apprêtes à renommer les tables **wallets**, **users** et **boutique_roles** "
                "(remplacées depuis longtemps par les tables `guild_*`).\n\n"
                "Aucune donnée n'est supprimée — les tables sont renommées (`archived_...`), "
                "réversible en cas de besoin.\n\n"
                "Ne fais ceci que si la migration vers les tables par serveur est validée depuis un moment."
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
            cancel_embed = discord.Embed(title="❌ Archivage annulé", color=discord.Color.red())
            set_bot_footer(cancel_embed, inter)
            await inter.response.edit_message(embed=cancel_embed, view=None)

        continue_btn.callback = continue_callback
        cancel_btn.callback = cancel_callback
        view.add_item(continue_btn)
        view.add_item(cancel_btn)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()
