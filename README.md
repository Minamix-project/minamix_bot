# MinamixBot

Python Discord bot with a per-guild economy, role shop, moderation tools,
absence tracking, and roleplay characters powered by webhooks.

## Requirements

- Docker with the Docker Compose plugin;
- a bot created in the [Discord Developer Portal](https://discord.com/developers/applications);
- the privileged **Message Content Intent** and **Server Members Intent**;
- the Discord permissions required by enabled features: view/send messages,
  manage roles, manage webhooks, manage messages, and ban members.

> Never publish a Discord token. If it appears in a message, log, or commit,
> revoke it immediately in the Developer Portal.

## Installation

1. Copy the configuration:

   ```bash
   cp .env.example .env
   ```

2. Replace passwords and set a newly generated token in `.env`.

3. Validate the configuration without starting services:

   ```bash
   docker compose config
   ```

4. Build and start the stack:

   ```bash
   docker compose up -d --build
   ```

The database schema and migrations are initialized automatically. A table,
migration, or module-loading failure stops startup instead of leaving a partial
bot running.

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | yes | — | Secret Discord bot token |
| `DISCORD_GUILD_IDS` | no | project defaults | Comma-separated allowed guild IDs |
| `DB_HOST` | yes | — | MySQL host, usually `db` in Compose |
| `DB_PORT` | no | `3306` | MySQL port |
| `DB_NAME` | yes | — | Database name |
| `DB_USER` | yes | — | Application database user |
| `DB_PASSWORD` | yes | — | Application database password |
| `MYSQL_ROOT_PASSWORD` | yes | — | MySQL container root password |
| `DB_POOL_MIN_SIZE` | no | `1` | Minimum pool size |
| `DB_POOL_MAX_SIZE` | no | `10` | Maximum pool size |
| `DB_POOL_RECYCLE_SECONDS` | no | `1800` | Connection recycling interval |
| `DB_CONNECT_TIMEOUT_SECONDS` | no | `10` | Connection timeout |
| `BACKUP_INTERVAL_SECONDS` | no | `21600` | Backup interval |
| `BACKUP_RETENTION_DAYS` | no | `14` | Backup retention period |
| `BACKUP_TEST_INTERVAL_SECONDS` | no | `86400` | Restore-test interval |
| `BACKUP_TEST_ROOT_PASSWORD` | no | internal default | Temporary restore database password |
| `LOG_LEVEL` | no | `INFO` | Python log level |

Variables use `NAME=value` syntax, never `NAME: value`. Use long, distinct
passwords for `DB_PASSWORD`, `MYSQL_ROOT_PASSWORD`, and
`BACKUP_TEST_ROOT_PASSWORD`.

## Permissions

Administrative commands require **Manage Server** or **Administrator**. RP
RP management commands use the same **Manage Server** or **Administrator**
permission. These rules are enforced both by Discord command visibility and by
the bot at runtime.

## Commands

### General and absence

| Command | Description |
| --- | --- |
| `/help` | Show the interactive help |
| `/status` | Show public bot status and information |
| `/changelog` | Show recent GitHub releases |
| `/afk` | Set your absence status |
| `/back` | Clear your absence status |
| `/absents` | List absent members — admin |
| `/activity <user>` | View a member's activity — admin |

### Economy and shop

| Command | Description |
| --- | --- |
| `/balance` | Show your balance |
| `/work` | Claim a reward using the configured cooldown |
| `/shop` | Show the paginated role shop |
| `/buy [number]` | Buy a role |
| `/leaderboard [page]` | Show the wealth leaderboard |
| `/transactions [user]` | View your history; admins may select another member |
| `/discoveries` | Show secret discoveries |
| `/economystats` | Show economy statistics — admin |
| `/economyconfig [...]` | Configure rewards, cooldowns, balances, and caps — admin |
| `/addmoney <user> <amount>` | Add currency — admin |
| `/removemoney <user> <amount>` | Remove currency — admin |
| `/additem <role> <price> <name> [exclusive] [description]` | Add a shop item — admin |
| `/edititem <number> [...]` | Edit a shop item — admin |
| `/removeitem <number>` | Remove an item with confirmation — admin |
| `/giveitem <number> <user> [deduct]` | Give an item, optionally charging the recipient — admin |
| `/resetbalances` | Reset balances after triple confirmation — admin |

Purchases re-read and lock the item and wallet in the database. A changed
price or deleted item invalidates an old confirmation. The `/work` reward and
cooldown are committed atomically.

### Moderation and operations

| Command | Description |
| --- | --- |
| `/warn <user> <reason>` | Warn a member — admin |
| `/warnings <user> [page]` | View warnings — admin |
| `/delwarn <user> <number>` | Delete a warning — admin |
| `/addantispam <channel>` | Enable automatic bans in a channel — admin |
| `/removeantispam <channel>` | Disable anti-spam — admin |
| `/listantispam` | List anti-spam channels — admin |
| `/addecoignore <channel>` | Exclude a channel from message rewards — admin |
| `/removeecoignore <channel>` | Re-enable message rewards — admin |
| `/listecoignore` | List excluded channels — admin |
| `/setlogs <channel>` | Configure general logs — admin |
| `/setwarnlogs <channel>` | Configure warning logs — admin |
| `/setafklogs <channel>` | Configure absence logs — admin |
| `/seterrorlogs <channel>` | Configure technical error logs — admin |
| `/config` | Show configured channels and migration status — admin |
| `/audit [author] [command] [days]` | View administrative actions — admin |
| `/health` | Check Discord and MySQL — admin |
| `/backupstatus` | Show the latest backup and restore test — admin |
| `/servers` | Show allowed guilds — admin |

Anti-spam logs message deletion and ban results separately. Technical failures
receive a short reference and can be sent to the channel configured with
`/seterrorlogs`.

### Roleplay

| Command | Description |
| --- | --- |
| `/roll <expression>` | Roll dice; use `/roll help` for syntax |
| `/rplist [user] [page]` | List characters |
| `/rpbourse [user]` | Show a character's Nax balance |
| `/rpcreate <user> <name> <prefix> <image>` | Create a character — admin |
| `/rpedit <user>` | Edit a name or prefix — admin |
| `/rpimage <user> <image>` | Change an image — admin |
| `/rpdelete <user>` | Delete a character — admin |
| `/setrpchannel <channel>` | Configure the RP announcement channel — admin |
| `/addnax <user> <amount>` | Add Nax — admin |
| `/removenax <user> <amount>` | Remove Nax — admin |

## Backups

The `backup` service creates periodic SQL dumps and removes files older than
`BACKUP_RETENTION_DAYS`. Dumps are created with owner-only permissions. The
`backup-test` service regularly restores the latest dump into a temporary
database and exposes its status to the bot.

The host `backups/` directory contains sensitive database data. Store it on an
encrypted disk, restrict host permissions, and keep an off-machine copy.

## Development and operations

```bash
make test      # run unit tests
make lint      # run Ruff and Python compilation checks
make status    # show container status
make logs      # follow bot logs
make restart   # recreate only the bot, without rebuilding
make deploy    # pull Git and rebuild bot and backup services
make stop      # stop application services
```

CI automatically runs linting, compilation, and tests on pushes and pull
requests.

## Architecture

```text
main.py
src/
  bot.py          # Discord, database, event, and command initialization
  config.py       # allowed guilds and roles
  commands/
    economie/
    general/
    moderation/
    rp/
  core/           # module loading and migrations
  events/         # messages, anti-spam, AFK, and RP
  migrations/     # versioned SQL migrations
  model/          # initial schema
  utils/           # database, economy, permissions, views, and logging
tests/
```

## Container security

The bot container runs as a non-root user with a read-only filesystem, a
temporary `/tmp`, no Linux capabilities, and `no-new-privileges`. Docker
images and Python dependencies are pinned for reproducible builds.
