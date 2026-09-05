import discord
from discord import Interaction
from discord.ui import Select

from src.utils.embed import set_bot_footer
from src.utils.permissions import is_admin


_GENERAL = (
    "`/afk` — Signaler une absence et sa durée\n"
    "`/back` — Mettre fin à ton absence\n"
    "`/status` — Voir l'état et la version du bot\n"
    "`/changelog` — Voir les dernières versions"
)

_ECONOMY = (
    "`/balance` — Consulter ton solde\n"
    "`/work` — Gagner des coins (une fois par semaine)\n"
    "`/shop` — Afficher la boutique du serveur\n"
    "`/buy [numéro]` — Acheter un rôle\n"
    "`/leaderboard` — Afficher le classement avec navigation\n"
    "`/discoveries` — Consulter tes découvertes secrètes\n"
    "`/transactions [user]` — Consulter l'historique économique"
)

_RP_PUBLIC = (
    "`/roll <expression>` — Lancer des dés (`/roll help` pour les exemples)\n"
    "`/rplist [user]` — Lister des personnages avec navigation\n"
    "`/rpbourse [user]` — Consulter la bourse Nax d'un personnage"
)

_RP_MANAGEMENT = (
    "`/rpcreate <user> <name> <prefix> <image>` — Créer un personnage\n"
    "`/rpedit <user>` — Modifier le nom ou le préfixe\n"
    "`/rpimage <user> <image>` — Changer l'image\n"
    "`/rpdelete <user>` — Supprimer un personnage"
)

_ADMIN_ECONOMY = (
    "`/addmoney <user> <montant>` — Ajouter des coins\n"
    "`/removemoney <user> <montant>` — Retirer des coins\n"
    "`/additem <role> <prix> <nom> [...]` — Ajouter un article\n"
    "`/edititem <numéro> [...]` — Modifier un article\n"
    "`/removeitem <numéro>` — Supprimer un article\n"
    "`/giveitem <numéro> <user> [déduire]` — Donner un article\n"
    "`/addnax <user> <montant>` — Ajouter des Nax\n"
    "`/removenax <user> <montant>` — Retirer des Nax\n"
    "`/economystats` — Afficher les statistiques économiques\n"
    "`/resetbalances` — Remettre les soldes du serveur à zéro\n"
    "`/economyconfig` — Configurer les gains, délais et plafonds"
)

_MODERATION = (
    "`/warn <user> <raison>` — Ajouter un avertissement\n"
    "`/warnings <user>` — Consulter les avertissements avec navigation\n"
    "`/delwarn <user> <numéro>` — Supprimer un avertissement\n"
    "`/absents` — Lister les membres absents\n"
    "`/activity <user>` — Consulter l'activité d'un membre\n"
    "`/addantispam <channel>` — Activer l'antispam dans un salon\n"
    "`/removeantispam <channel>` — Désactiver l'antispam\n"
    "`/listantispam` — Lister les salons protégés\n"
    "`/addecoignore <channel>` — Ignorer un salon pour les gains\n"
    "`/removeecoignore <channel>` — Réactiver les gains dans un salon\n"
    "`/listecoignore` — Lister les salons économiques ignorés"
)

_SYSTEM = (
    "`/config` — Afficher les salons configurés\n"
    "`/setlogs <channel>` — Définir les logs généraux\n"
    "`/setafklogs <channel>` — Définir les logs d'absence\n"
    "`/setwarnlogs <channel>` — Définir les logs d'avertissement\n"
    "`/setrpchannel <channel>` — Définir le salon des annonces RP\n"
    "`/servers` — Afficher les serveurs autorisés\n"
    "`/health` — Vérifier Discord et MySQL\n"
    "`/backupstatus` — Vérifier le dernier dump et sa restauration\n"
    "`/audit [...]` — Consulter les actions administratives\n"
    "`/seterrorlogs <channel>` — Définir le salon des erreurs techniques"
)


class HelpView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "❌ Lance `/help` toi-même pour consulter les commandes.", ephemeral=True
        )
        return False

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.HTTPException, discord.NotFound):
                pass


async def register(bot):
    @bot.tree.command(name="help", description="Afficher les commandes disponibles.")
    async def help(interaction: Interaction):
        admin = is_admin(interaction.user)

        options = [
            discord.SelectOption(label="Pour commencer", value="general", emoji="👋"),
            discord.SelectOption(label="Économie", value="economy", emoji="💰"),
            discord.SelectOption(label="Roleplay", value="rp", emoji="🎭"),
        ]
        if admin:
            options.append(discord.SelectOption(
                label="Gestion RP", value="rp_management", emoji="📝"
            ))
        if admin:
            options.extend([
                discord.SelectOption(label="Admin · Économie", value="admin_economy", emoji="🔒"),
                discord.SelectOption(label="Admin · Modération", value="moderation", emoji="🛡️"),
                discord.SelectOption(label="Admin · Configuration", value="system", emoji="⚙️"),
            ])

        pages = {
            "general": ("👋 Pour commencer", _GENERAL, discord.Color.blurple()),
            "economy": ("💰 Économie", _ECONOMY, discord.Color.gold()),
            "rp": ("🎭 Roleplay", _RP_PUBLIC, discord.Color.purple()),
            "rp_management": ("📝 Gestion RP", _RP_MANAGEMENT, discord.Color.purple()),
            "admin_economy": ("🔒 Administration · Économie", _ADMIN_ECONOMY, discord.Color.red()),
            "moderation": ("🛡️ Administration · Modération", _MODERATION, discord.Color.red()),
            "system": ("⚙️ Administration · Configuration", _SYSTEM, discord.Color.red()),
        }

        select = Select(placeholder="Choisis une catégorie…", options=options)
        view = HelpView(interaction.user.id)

        async def callback(inter: Interaction):
            title, description, color = pages[select.values[0]]
            embed = discord.Embed(title=title, description=description, color=color)
            set_bot_footer(embed, inter)
            await inter.response.edit_message(embed=embed, view=view)

        select.callback = callback
        view.add_item(select)

        access = "Les catégories administrateur sont affichées selon tes permissions."
        embed = discord.Embed(
            title="📖 Aide du bot",
            description=f"Choisis une catégorie ci-dessous.\n{access}",
            color=discord.Color.blurple(),
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()
