import discord
from discord import Interaction, Member, app_commands

from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.format import format_amount
from src.utils.transfers import transfer_money, transfer_nax
from src.commands.rp.rpnax import NAX_EMOJI


ERRORS = {"invalid": "Le montant doit être positif et le destinataire différent de vous.", "cooldown": "Vous devez attendre avant un nouveau transfert.", "daily_limit": "Ce transfert dépasserait votre limite quotidienne.", "insufficient": "Votre solde est insuffisant.", "recipient_cap": "Ce transfert dépasserait le plafond du destinataire.", "character_missing": "Un personnage n'existe plus.", "character_owner": "Les personnages ne correspondent plus aux joueurs."}


async def _characters(guild_id, user_id):
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute("SELECT id, name, nax_balance FROM rp_characters WHERE guild_id = %s AND user_id = %s ORDER BY created_at", (guild_id, user_id))
            return await cursor.fetchall()
    finally:
        db.close()


def _error_description(status, details, currency):
    unit = "💰" if currency == "money" else NAX_EMOJI
    if status == "daily_limit" and details:
        return (f"Limite quotidienne : **{format_amount(details['daily_limit'])} {unit}**\n"
                f"Déjà transféré : **{format_amount(details['sent_today'])} {unit}**\n"
                f"Montant restant : **{format_amount(details['remaining'])} {unit}**")
    if status == "cooldown" and details:
        seconds = max(1, details['cooldown_remaining'])
        return f"Vous devez attendre encore **{seconds // 60} min {seconds % 60} s** avant un nouveau transfert."
    return ERRORS.get(status, "Une erreur est survenue.")


async def _execute(interaction, recipient, amount, reason, currency, sender_character=None, recipient_character=None):
    db = await get_db_connection()
    try:
        if currency == "money":
            result = await transfer_money(db, interaction.guild_id, interaction.user.id, recipient.id, amount, reason)
        else:
            result = await transfer_nax(db, interaction.guild_id, interaction.user.id, recipient.id, sender_character, recipient_character, amount, reason)
    finally:
        db.close()
    ok, status, sender_balance, _ = result
    if not ok:
        embed = discord.Embed(title="❌ Transfert impossible", description=_error_description(status, sender_balance, currency), color=discord.Color.red())
    else:
        unit = "💰" if currency == "money" else NAX_EMOJI
        embed = discord.Embed(title="✅ Transfert effectué", description=f"**{format_amount(amount)} {unit}** envoyés à {recipient.mention}\nMotif : {reason}\nVotre nouveau solde : **{format_amount(sender_balance)} {unit}**", color=discord.Color.green())
    set_bot_footer(embed, interaction)
    return embed


class CurrencyView(discord.ui.View):
    def __init__(self, owner_id, recipient, amount, reason):
        super().__init__(timeout=180)
        self.owner_id, self.recipient, self.amount, self.reason = owner_id, recipient, amount, reason
        money = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji="💰")
        nax = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=discord.PartialEmoji.from_str(NAX_EMOJI))
        money.callback = self.select_money
        nax.callback = self.select_nax
        self.add_item(money)
        self.add_item(nax)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Cette sélection ne vous appartient pas.", ephemeral=True)
            return False
        return True

    async def select_money(self, interaction):
        embed = await _execute(interaction, self.recipient, self.amount, self.reason, "money")
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    async def select_nax(self, interaction):
        senders = await _characters(interaction.guild_id, interaction.user.id)
        recipients = await _characters(interaction.guild_id, self.recipient.id)
        if not senders or not recipients:
            await interaction.response.edit_message(content="❌ Vous et le destinataire devez chacun avoir un personnage RP.", view=None)
        elif len(senders) == len(recipients) == 1:
            embed = await _execute(interaction, self.recipient, self.amount, self.reason, "nax", senders[0][0], recipients[0][0])
            await interaction.response.edit_message(content=None, embed=embed, view=None)
        else:
            await interaction.response.edit_message(content="Choisissez votre personnage source.", view=NaxTransferView(self.owner_id, self.recipient, self.amount, self.reason, senders, recipients))


class NaxTransferView(discord.ui.View):
    def __init__(self, owner_id, recipient, amount, reason, senders, recipients):
        super().__init__(timeout=180)
        self.owner_id, self.recipient, self.amount, self.reason, self.recipients = owner_id, recipient, amount, reason, recipients
        self.sender_id = None
        self.select = discord.ui.Select(placeholder="Choisissez votre personnage source", options=[discord.SelectOption(label=n[:100], value=str(i), description=f"{format_amount(b)} NAX") for i, n, b in senders[:25]])
        self.select.callback = self.source
        self.add_item(self.select)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Cette sélection ne vous appartient pas.", ephemeral=True)
            return False
        return True

    async def source(self, interaction):
        self.sender_id = int(self.select.values[0])
        self.select.options = [discord.SelectOption(label=n[:100], value=str(i), description=f"{format_amount(b)} NAX") for i, n, b in self.recipients[:25]]
        self.select.placeholder = f"Choisissez le personnage de {self.recipient.display_name}"
        self.select.callback = self.target
        await interaction.response.edit_message(content="Choisissez le personnage destinataire.", view=self)

    async def target(self, interaction):
        embed = await _execute(interaction, self.recipient, self.amount, self.reason, "nax", self.sender_id, int(self.select.values[0]))
        self.clear_items()
        await interaction.response.edit_message(content=None, embed=embed, view=self)


async def register(bot):
    @bot.tree.command(name="pay", description="Envoyer de largent ou des NAX à un joueur")
    @app_commands.describe(user="Destinataire", amount="Montant à envoyer", reason="Motif du transfert")
    async def pay(interaction: Interaction, user: Member, amount: int, reason: str):
        if not interaction.guild_id or not reason.strip() or amount <= 0 or user.id == interaction.user.id:
            await interaction.response.send_message("❌ Le destinataire, un montant positif et un motif sont obligatoires.", ephemeral=True)
            return
        await interaction.response.send_message("Choisissez la devise.", view=CurrencyView(interaction.user.id, user, amount, reason.strip()), ephemeral=True)
