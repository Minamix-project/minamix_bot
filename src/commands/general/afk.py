import discord
from discord import Interaction
from datetime import datetime, timezone
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.views import ExpiringView

_REASONS = [
    ("Santé", "🏥"),
    ("Famille", "👨‍👩‍👧"),
    ("Voyage", "✈️"),
    ("Travail / Études", "💼"),
    ("Repos", "😴"),
    ("Urgence", "🚨"),
    ("Indisponible", "🔕"),
    ("Ne vous regarde pas", "🔒"),
]


class _AfkDatesModal(discord.ui.Modal, title="Définir la période d'absence"):
    start_time = discord.ui.TextInput(
        label="Début de l'absence",
        placeholder="JJ/MM/AAAA HH:MM — laisser vide = maintenant",
        required=False,
        max_length=16,
    )
    end_time = discord.ui.TextInput(
        label="Fin de l'absence",
        placeholder="JJ/MM/AAAA HH:MM — laisser vide si indéterminé",
        required=False,
        max_length=16,
    )

    def __init__(self, reason: str):
        super().__init__()
        self.reason = reason

    async def on_submit(self, interaction: Interaction):
        start = None
        end = None

        raw_start = self.start_time.value.strip()
        raw_end = self.end_time.value.strip()

        if raw_start:
            try:
                start = datetime.strptime(raw_start, "%d/%m/%Y %H:%M")
            except ValueError:
                embed = discord.Embed(
                    title="❌ Format invalide",
                    description="Format attendu : `JJ/MM/AAAA HH:MM` (ex: `25/12/2025 18:00`).",
                    color=discord.Color.red()
                )
                set_bot_footer(embed, interaction)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        if raw_end:
            try:
                end = datetime.strptime(raw_end, "%d/%m/%Y %H:%M")
            except ValueError:
                embed = discord.Embed(
                    title="❌ Format invalide",
                    description="Format attendu : `JJ/MM/AAAA HH:MM` (ex: `25/12/2025 18:00`).",
                    color=discord.Color.red()
                )
                set_bot_footer(embed, interaction)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        if start and end and end < start:
            await interaction.response.send_message("❌ La fin doit être postérieure au début.", ephemeral=True)
            return

        member = interaction.user
        original_nick = member.nick or member.name

        new_nick = f"Absent · {member.display_name}"
        if len(new_nick) > 32:
            new_nick = new_nick[:32]

        try:
            await member.edit(nick=new_nick)
        except discord.Forbidden:
            pass

        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "INSERT INTO afk_users (user_id, guild_id, original_nick, reason, start_time, end_time) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE reason=%s, original_nick=%s, start_time=%s, end_time=%s",
            (
                member.id, interaction.guild.id, original_nick, self.reason,
                start or datetime.now(timezone.utc).replace(tzinfo=None), end,
                self.reason, original_nick, start or datetime.now(timezone.utc).replace(tzinfo=None), end,
            )
        )
        await db.commit()
        await cursor.close()
        db.close()

        start_str = f"<t:{int(start.timestamp())}:f>" if start else "maintenant"
        end_str = f"<t:{int(end.timestamp())}:f>" if end else "indéfinie"

        embed = discord.Embed(
            title="💤 Statut absent activé",
            description=f"Raison : **{self.reason}**\nDébut : {start_str}\nFin : {end_str}",
            color=discord.Color.greyple()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Send to AFK logs
        from src.events.afk_handler import send_afk_log
        await send_afk_log(interaction.client, interaction.guild.id, discord.Embed(
            title="💤 Absence déclarée",
            description=(
                f"{member.mention} s'est déclaré(e) absent(e).\n"
                f"Raison : **{self.reason}**\n"
                f"Début : {start_str} — Fin : {end_str}"
            ),
            color=discord.Color.greyple()
        ).set_thumbnail(url=member.display_avatar.url))


async def register(bot):
    @bot.tree.command(name="afk", description="Définir ton statut absent.")
    async def afk(interaction: Interaction):
        options = [
            discord.SelectOption(label=label, emoji=emoji, value=label)
            for label, emoji in _REASONS
        ]
        select = discord.ui.Select(placeholder="Choisis une raison...", options=options)

        async def callback(inter: Interaction):
            reason = select.values[0]
            await inter.response.send_modal(_AfkDatesModal(reason=reason))

        select.callback = callback
        view = ExpiringView(timeout=60, owner_id=interaction.user.id)
        view.add_item(select)

        await interaction.response.send_message(
            "Quelle est la raison de ton absence ?",
            view=view,
            ephemeral=True
        )
        view.message = await interaction.original_response()
