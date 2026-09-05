from discord import Interaction
from discord.ui import Select
import discord
from src.utils.embed import set_bot_footer
from src.utils.permissions import is_admin
from src.utils.views import ExpiringView

_GENERAL = (
    "`/afk` — Définir ton statut absent (raison + période)\n"
    "`/back` — Annuler ton statut absent\n"
    "`/status` — Voir le statut et les infos du bot\n"
    "`/changelog` — Voir les dernières releases GitHub"
)

_ECONOMY = (
    "`/balance` — Voir votre solde\n"
    "`/work` — Gagner des coins (cooldown : 1 semaine)\n"
    "`/shop` — Voir les rôles disponibles à l'achat\n"
    "`/buy [numéro]` — Acheter un rôle (liste déroulante si numéro omis)\n"
    "`/leaderboard` — Top 10 des utilisateurs les plus riches\n"
    "`/discoveries` — Voir tes découvertes secrètes"
)

_ADMIN = (
    "`/addmoney <user> <montant>` — Ajouter des coins à un utilisateur\n"
    "`/removemoney <user> <montant>` — Retirer des coins à un utilisateur\n"
    "`/additem <role> <prix> <nom> [exclusif] [description]` — Ajouter un rôle à la boutique\n"
    "`/edititem <numéro> [prix] [nom] [description] [exclusif]` — Modifier un article\n"
    "`/removeitem <numéro>` — Supprimer un article de la boutique\n"
    "`/giveitem <numéro> <user>` — Donner un article à un utilisateur\n"
    "`/resetbalances` — Remettre tous les soldes à zéro\n"
    "`/economystats` — Voir les statistiques de l'économie"
)

_RP = (
    "`/roll <expression>` — Lancer des dés (`/roll help` pour la syntaxe)\n"
    "`/rpcreate <user> <name> <prefix> <image>` — Créer un personnage RP\n"
    "`/rpedit <user>` — Modifier nom ou préfixe (sélection + modal)\n"
    "`/rpimage <user> <image>` — Changer l'image d'un personnage\n"
    "`/rpdelete <user>` — Supprimer un personnage (sélection)\n"
    "`/rpbourse [user]` — Voir la bourse Nax d'un personnage\n"
    "`/addnax <user> <montant>` — Ajouter des Nax à un personnage\n"
    "`/removenax <user> <montant>` — Retirer des Nax à un personnage\n"
    "`/rplist [user]` — Lister les personnages d'un utilisateur\n"
    "`/setrpchannel <channel>` — Définir le channel d'annonce RP"
)

_MODERATION = (
    "`/setlogs <channel>` — Définir le channel de logs\n"
    "`/setafklogs <channel>` — Définir le channel de logs des absences\n"
    "`/setwarnlogs <channel>` — Définir le channel de logs des warns\n"
    "`/warn <user> <raison>` — Avertir un membre\n"
    "`/warnings <user>` — Voir l'historique des warns d'un membre\n"
    "`/delwarn <user> <numéro>` — Supprimer un avertissement\n"
    "`/absents` — Liste des membres absents par ordre de date\n"
    "`/activity <user>` — Voir l'activité d'un membre\n"
    "`/addantispam <channel>` — Ajouter un channel anti-spam (ban instantané)\n"
    "`/removeantispam <channel>` — Retirer un channel du mode anti-spam\n"
    "`/listantispam` — Lister les channels anti-spam actifs\n"
    "`/config` — Voir les salons configurés\n"
    "`/servers` — Voir les serveurs autorisés\n"
    "`/health` — Vérifier Discord et MySQL\n"
    "`/backupstatus` — Voir le dernier dump SQL"
)

async def register(bot):
    @bot.tree.command(name="help", description="Affiche les commandes du bot.")
    async def help(interaction: Interaction):
        is_admin_user = is_admin(interaction.user)

        options = [
            discord.SelectOption(label="Général", value="general", description="Commandes générales", emoji="🌐"),
            discord.SelectOption(label="Économie", value="economy", description="Commandes d'économie", emoji="💰"),
        ]
        options.append(
            discord.SelectOption(label="Roleplay", value="rp", description="Commandes RP", emoji="🎭")
        )
        if is_admin:
            options.append(
                discord.SelectOption(label="Administration", value="admin", description="Commandes admin", emoji="🔒")
            )
            options.append(
                discord.SelectOption(label="Modération", value="moderation", description="Commandes de modération", emoji="🛡️")
            )

        select = Select(placeholder="Choisir une catégorie...", options=options)

        async def callback(inter: Interaction):
            val = select.values[0]
            if val == "general":
                embed = discord.Embed(title="🌐 Général", description=_GENERAL, color=discord.Color.blurple())
            elif val == "economy":
                embed = discord.Embed(title="💰 Économie", description=_ECONOMY, color=discord.Color.gold())
            elif val == "rp":
                embed = discord.Embed(title="🎭 Roleplay", description=_RP, color=discord.Color.purple())
            elif val == "admin":
                embed = discord.Embed(title="🔒 Administration", description=_ADMIN, color=discord.Color.red())
            else:
                embed = discord.Embed(title="🛡️ Modération", description=_MODERATION, color=discord.Color.blurple())
            set_bot_footer(embed, inter)
            await inter.response.send_message(embed=embed, ephemeral=True)

        select.callback = callback
        view = ExpiringView()
        view.add_item(select)

        embed = discord.Embed(
            title="📖 Aide",
            description="Sélectionne une catégorie pour voir les commandes disponibles.",
            color=discord.Color.blurple()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()
