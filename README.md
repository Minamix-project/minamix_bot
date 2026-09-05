# MinamixBot

Bot Discord communautaire en Python comprenant une économie par serveur, une
boutique de rôles, des outils de modération, un système d'absence et des
personnages RP via webhooks.

## Prérequis

- Docker avec le plugin Docker Compose ;
- un bot créé dans le [Discord Developer Portal](https://discord.com/developers/applications) ;
- les intents privilégiés **Message Content Intent** et **Server Members Intent** ;
- les permissions Discord nécessaires au bot : voir et envoyer des messages,
  gérer les rôles, gérer les webhooks, gérer les messages et bannir des membres.

> Ne publiez jamais le token Discord. S'il apparaît dans un message, un log ou
> un commit, réinitialisez-le immédiatement dans le Developer Portal.

## Installation

1. Copier la configuration :

   ```bash
   cp .env.example .env
   ```

2. Remplacer les mots de passe et renseigner le nouveau token dans `.env`.

3. Vérifier la configuration sans lancer de service :

   ```bash
   docker compose config
   ```

4. Construire et démarrer l'ensemble :

   ```bash
   docker compose up -d --build
   ```

La base est initialisée et les migrations SQL sont appliquées automatiquement
au démarrage. Une erreur de création de table, de migration ou de chargement
d'un module interrompt maintenant le démarrage.

## Configuration

| Variable | Requise | Valeur par défaut | Description |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | oui | — | Token secret du bot Discord |
| `DISCORD_GUILD_IDS` | non | IDs historiques du projet | Serveurs autorisés, séparés par des virgules |
| `RP_ALLOWED_ROLE_IDS` | non | rôles historiques du projet | Rôles autorisés à gérer le RP |
| `DB_HOST` | oui | — | Hôte MySQL, généralement `db` avec Compose |
| `DB_PORT` | non | `3306` | Port MySQL |
| `DB_NAME` | oui | — | Nom de la base |
| `DB_USER` | oui | — | Utilisateur applicatif |
| `DB_PASSWORD` | oui | — | Mot de passe applicatif |
| `MYSQL_ROOT_PASSWORD` | oui | — | Mot de passe root utilisé par le conteneur MySQL |
| `DB_POOL_MIN_SIZE` | non | `1` | Taille minimale du pool |
| `DB_POOL_MAX_SIZE` | non | `10` | Taille maximale du pool |
| `DB_POOL_RECYCLE_SECONDS` | non | `1800` | Renouvellement des connexions |
| `DB_CONNECT_TIMEOUT_SECONDS` | non | `10` | Délai maximal de connexion |
| `BACKUP_INTERVAL_SECONDS` | non | `21600` | Intervalle entre les dumps |
| `BACKUP_RETENTION_DAYS` | non | `14` | Durée de conservation |
| `BACKUP_TEST_INTERVAL_SECONDS` | non | `86400` | Intervalle des tests de restauration |
| `BACKUP_TEST_ROOT_PASSWORD` | non | valeur interne | Mot de passe de la base temporaire de restauration |
| `LOG_LEVEL` | non | `INFO` | Niveau des logs Python |

La syntaxe d'une variable est toujours `NOM=valeur`, jamais
`NOM: valeur`. Utilisez des mots de passe longs et différents pour
`DB_PASSWORD`, `MYSQL_ROOT_PASSWORD` et `BACKUP_TEST_ROOT_PASSWORD`.

## Permissions des commandes

Les commandes d'administration exigent la permission Discord **Gérer le
serveur** ou **Administrateur**. Les commandes de gestion RP acceptent aussi
les rôles déclarés dans `RP_ALLOWED_ROLE_IDS`. Ces règles sont contrôlées à
la fois par Discord et par le bot.

## Commandes

### Général et absence

| Commande | Description |
| --- | --- |
| `/help` | Afficher l'aide interactive |
| `/status` | Afficher l'état public et les informations du bot |
| `/changelog` | Afficher les dernières versions GitHub |
| `/afk` | Déclarer une absence |
| `/back` | Annuler son absence |
| `/absents` | Lister les membres absents — admin |
| `/activity <user>` | Consulter l'activité d'un membre — admin |

### Économie et boutique

| Commande | Description |
| --- | --- |
| `/balance` | Afficher son solde |
| `/work` | Recevoir un gain selon le cooldown configuré |
| `/shop` | Afficher la boutique avec pagination et boutons |
| `/buy [numero]` | Acheter un rôle |
| `/leaderboard [page]` | Afficher le classement |
| `/transactions [user]` | Consulter son historique ; un admin peut viser un autre membre |
| `/discoveries` | Afficher les découvertes secrètes |
| `/economystats` | Afficher les statistiques économiques — admin |
| `/economyconfig [...]` | Configurer gains, cooldown, solde initial et plafond — admin |
| `/addmoney <user> <montant>` | Ajouter de l'argent — admin |
| `/removemoney <user> <montant>` | Retirer de l'argent — admin |
| `/additem <role> <prix> <nom> [exclusif] [description]` | Ajouter un article — admin |
| `/edititem <numero> [...]` | Modifier un article — admin |
| `/removeitem <numero>` | Supprimer un article avec confirmation — admin |
| `/giveitem <numero> <user> [deduire]` | Donner un article, avec débit optionnel — admin |
| `/resetbalances` | Réinitialiser les soldes après triple confirmation — admin |

Les achats relisent et verrouillent l'article et le portefeuille en base. Un
prix modifié ou un article supprimé invalide donc une ancienne confirmation.
Le gain de `/work` et son cooldown sont enregistrés dans une transaction
atomique.

### Modération et exploitation

| Commande | Description |
| --- | --- |
| `/warn <user> <reason>` | Avertir un membre — admin |
| `/warnings <user> [page]` | Consulter ses avertissements — admin |
| `/delwarn <user> <numero>` | Supprimer un avertissement — admin |
| `/addantispam <channel>` | Activer le ban automatique dans un salon — admin |
| `/removeantispam <channel>` | Désactiver l'anti-spam — admin |
| `/listantispam` | Lister les salons anti-spam — admin |
| `/addecoignore <channel>` | Exclure un salon des gains par message — admin |
| `/removeecoignore <channel>` | Réautoriser les gains dans un salon — admin |
| `/listecoignore` | Lister les salons exclus — admin |
| `/setlogs <channel>` | Configurer les logs généraux — admin |
| `/setwarnlogs <channel>` | Configurer les logs d'avertissements — admin |
| `/setafklogs <channel>` | Configurer les logs d'absence — admin |
| `/seterrorlogs <channel>` | Configurer les erreurs techniques — admin |
| `/config` | Afficher les salons configurés et l'état des migrations — admin |
| `/audit [auteur] [commande] [depuis_jours]` | Consulter les actions administratives — admin |
| `/health` | Vérifier Discord et MySQL — admin |
| `/backupstatus` | Afficher le dernier dump et son test de restauration — admin |
| `/servers` | Afficher les serveurs autorisés — admin |

L'anti-spam journalise séparément la suppression du message et le résultat du
ban. Les échecs techniques reçoivent une référence courte et peuvent être
envoyés au salon configuré par `/seterrorlogs`.

### Roleplay

| Commande | Description |
| --- | --- |
| `/roll <expression>` | Lancer des dés ; utiliser `/roll help` pour la syntaxe |
| `/rplist [user] [page]` | Lister les personnages |
| `/rpbourse [user]` | Afficher la bourse Nax d'un personnage |
| `/rpcreate <user> <name> <prefix> <image>` | Créer un personnage — gestionnaire RP |
| `/rpedit <user>` | Modifier le nom ou le préfixe — gestionnaire RP |
| `/rpimage <user> <image>` | Modifier l'image — gestionnaire RP |
| `/rpdelete <user>` | Supprimer un personnage — gestionnaire RP |
| `/setrpchannel <channel>` | Configurer le salon d'annonce RP — admin |
| `/addnax <user> <montant>` | Ajouter des Nax — admin |
| `/removenax <user> <montant>` | Retirer des Nax — admin |

## Sauvegardes

Le service `backup` effectue un dump périodique et supprime les fichiers plus
anciens que `BACKUP_RETENTION_DAYS`. Les dumps sont créés avec des permissions
réservées à leur propriétaire. Le service `backup-test` restaure régulièrement
le dernier dump dans une base temporaire et publie son état au bot.

Le dossier hôte `backups/` contient des données sensibles : placez-le sur un
disque chiffré, limitez ses permissions et prévoyez une copie hors machine.

## Développement et exploitation

```bash
make test      # tests unitaires
make lint      # Ruff et compilation Python
make status    # état des conteneurs
make logs      # logs du bot
make restart   # recréer uniquement le bot, sans rebuild
make deploy    # pull Git puis rebuild du bot et des services de sauvegarde
make stop      # arrêter les services applicatifs
```

La CI exécute automatiquement le lint, la compilation et les tests sur les
pushes et pull requests.

## Architecture

```text
main.py
src/
  bot.py          # initialisation Discord, DB, événements et commandes
  config.py       # configuration des serveurs et rôles autorisés
  commands/
    economie/
    general/
    moderation/
    rp/
  core/           # chargement des modules et migrations
  events/         # messages, anti-spam, AFK et RP
  migrations/     # migrations SQL versionnées
  model/          # schéma initial
  utils/          # DB, économie, permissions, vues et logs
tests/
```

## Sécurité du conteneur

Le conteneur du bot utilise un utilisateur non-root, un système de fichiers en
lecture seule, un `/tmp` temporaire, aucune capability Linux et
`no-new-privileges`. Les images Docker et les dépendances Python sont figées
pour rendre les builds reproductibles.
