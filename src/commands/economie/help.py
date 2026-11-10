import discord
from discord import Interaction
from discord.ui import Select

from src.utils.embed import set_bot_footer
from src.utils.dice import get_help as get_dice_help
from src.utils.permissions import is_admin


ADMIN_HELP_CATEGORIES = frozenset({"rp_management", "admin_economy", "moderation", "system", "message_history"})


_GENERAL = (
    "Panneau de support : ouvre un ticket privé depuis le menu du salon support.\n"
    "`/ticket close <reason>` · `/ticket transcript` · `/ticket info` — Gérer ton ticket\n"
    "`/reminder create|list|edit|delete` — Programmer et gérer tes rappels\n"
    "`/afk` — Signaler une absence et sa durée\n"
    "`/back` — Mettre fin à ton absence\n"
    "`/status` — Voir l'état et la version du bot\n"
    "`/changelog` — Voir les dernières versions"
)

_ECONOMY = (
    "`/balance` — Consulter ton solde\n"
    "`/work` — Gagner des coins (une fois par semaine)\n"
    "`/pay <user> <amount> <reason>` — Envoyer des coins ou des NAX à un joueur (choix de la devise)\n"
    "`/shop` — Afficher la boutique du serveur\n"
    "`/buy [numéro]` — Acheter un rôle\n"
    "`/leaderboard` — Afficher le classement avec navigation\n"
    "`/discoveries` — Consulter tes découvertes secrètes\n"
    "`/transactions [user]` — Consulter l'historique économique"
)

_RP_PUBLIC = (
    "`/rplist [user]` — Lister des personnages avec navigation\n"
    "`/rpbourse [user]` — Consulter la bourse Nax d'un personnage\n"
    "`/pay <user> <amount> <reason>` — Transférer des NAX entre personnages RP (choisir la devise NAX)"
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
    "`/economyconfig` — Configurer les gains, délais, plafonds et limites des transferts"
)

_MODERATION = (
    "`/ticket add|remove <user>` · `/ticket rename <name>` · `/ticket reopen` — Gérer un ticket\n"
    "`/ticket link <user>` — Lier un ticket à un utilisateur concerné\n"
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

_MESSAGE_HISTORY = (
    "`/messagehistory recent [channel] [user] [event]` — Voir les changements et ouvrir les versions depuis le menu\n"
    "`/messagehistory view <message_id> [channel]` — Consulter les versions conservées d'un message\n"
    "`/messagehistory status` — Voir la conservation et les limites"
)

_MESSAGE_HISTORY_ADMIN = (
    "`/messagehistory import [channel] [limit]` — Importer des messages récents\n"
    "`/messagehistory configure [...]` — Régler la conservation de l'historique\n"
    "`/messagehistory purge <channel> [...]` — Effacer des versions stockées (confirmation requise)"
)

_MESSAGE_HISTORY_ACCESS = (
    "Réponses privées ; accès au salon d'origine vérifié. "
    "Les messages des bots, applications et webhooks ne sont pas suivis. "
    "Toutes les commandes de cette rubrique sont réservées aux membres ayant "
    "« Administrateur » ou « Gérer le serveur »."
)

_SYSTEM = (
    "`/ticket panel <channel> <category> <staff_role> [logs_channel] [title] [text]` — Configurer le support\n"
    "`/ticket purge` — Supprimer tous les tickets et leurs données ; confirmation requise\n"
    "`/ticket reconcile <channel_id> <reason>` — Régulariser un ticket dont le salon a été supprimé\n"
    "`/config` — Afficher les salons configurés\n"
    "`/setlogs <channel>` — Définir les logs généraux\n"
    "`/setdevlog <channel>` — Choisir le salon du devlog du bot\n"
    "`/devlog [version] [preview]` — Publier ou prévisualiser les versions GitHub ; correctifs regroupés\n"
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
            discord.SelectOption(label="Dés", value="dice", emoji="🎲"),
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
        if admin:
            options.append(discord.SelectOption(label="Admin · Suivi des messages", value="message_history", emoji="📋"))

        history_help = _MESSAGE_HISTORY + "\n\n**Gestion de l'historique — administration**\n" + _MESSAGE_HISTORY_ADMIN
        history_help += "\n\n" + _MESSAGE_HISTORY_ACCESS

        pages = {
            "general": ("👋 Pour commencer", _GENERAL, discord.Color.blurple()),
            "economy": ("💰 Économie", _ECONOMY, discord.Color.gold()),
            "dice": ("🎲 Aide — Lancers de dés", get_dice_help(), discord.Color.blurple()),
            "rp": ("🎭 Roleplay", _RP_PUBLIC, discord.Color.purple()),
            "rp_management": ("📝 Gestion RP", _RP_MANAGEMENT, discord.Color.purple()),
            "admin_economy": ("🔒 Administration · Économie", _ADMIN_ECONOMY, discord.Color.red()),
            "moderation": ("🛡️ Administration · Modération", _MODERATION, discord.Color.red()),
            "system": ("⚙️ Administration · Configuration", _SYSTEM, discord.Color.red()),
            "message_history": ("📋 Administration · Suivi des messages", history_help, discord.Color.red()),
        }

        select = Select(placeholder="Choisis une catégorie…", options=options)
        view = HelpView(interaction.user.id)

        async def callback(inter: Interaction):
            category = select.values[0]
            if category in ADMIN_HELP_CATEGORIES and not is_admin(inter.user):
                await inter.response.send_message(
                    "❌ Cette rubrique est réservée aux membres ayant « Administrateur » ou « Gérer le serveur ».",
                    ephemeral=True,
                )
                return
            title, description, color = pages[category]
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
