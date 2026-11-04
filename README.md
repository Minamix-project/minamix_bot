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
| `BACKUP_TEST_ROOT_PASSWORD` | yes when backup tests are enabled | — | Temporary restore database password |
| `LOG_LEVEL` | no | `INFO` | Python log level |

Variables use `NAME=value` syntax, never `NAME: value`. Use long, distinct
passwords for `DB_PASSWORD`, `MYSQL_ROOT_PASSWORD`, and
`BACKUP_TEST_ROOT_PASSWORD`.

## Permissions

Administrative commands require **Manage Server** or **Administrator**. RP
management commands use the same **Manage Server** or **Administrator**
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
| `/reminder create <when> <text> [...]` | Schedule a reminder, delivered by DM by default |
| `/reminder list` | List your pending reminders and delivery failures in this server |
| `/reminder edit <reminder_id> [...]` | Update one of your pending or failed reminders |
| `/reminder delete <reminder_id>` | Delete one of your pending or failed reminders |

### Reminders

Reminder command and option names follow the bot's English naming convention.
Descriptions, choice labels, and bot messages are in French.
Use a duration (`2h`, `1j 30m`, `1sem`), a date and time
(`15/09/2027 20:00` or `2027-09-15 20:00`), `demain 18:00`,
`aujourd'hui 18:00`, or a time such as `18:00` for today. Existing English
duration units (`d`, `w`) and day names (`today`, `tomorrow`) remain accepted.
Dates use **Europe/Brussels** unless you provide an IANA `timezone`, such as
`UTC` or `America/Montreal`. Durations measure elapsed time. Past dates,
invalid dates, ambiguous/nonexistent daylight-saving times, and schedules more
than five years ahead are rejected. Discord displays confirmations in each
reader's local timezone.

```text
/reminder create when:2h text:Vérifier les annonces
/reminder create when:demain 18:00 text:Réunion du staff delivery:Salon actuel category:Réunion du staff
/reminder create when:15/09/2027 20:00 text:Événement de guilde channel:#evenements recipients:@Alice @Bob category:Événement RP
/reminder edit reminder_id:42 when:3h text:Nouvel horaire de réunion
/reminder edit reminder_id:42 recipients:aucun mention:false
/reminder delete reminder_id:42
```

Choose `delivery:Message privé` for a private reminder, `delivery:Salon actuel` for the
current server text channel, or a `channel` for another text channel. Selecting a
channel implies channel delivery when `delivery` is omitted. The creator must
be able to view and send messages there; the bot additionally needs Embed Links.
Threads and non-text channels are not supported. All management responses are
ephemeral, and members can only list, edit, or delete their own reminders in the
current server. A reminder being sent cannot be edited or deleted.

`mention` controls the creator's mention (enabled by default). `recipients`
accepts up to ten additional member mentions or IDs separated by spaces or
commas, for channel delivery only. Every selected member must be able to view
the destination. Roles, `@everyone`, and unselected users are never pinged.
Switching to DM clears additional recipients; use `recipients:aucun` to clear
them explicitly (`none` remains accepted). Text is always free-form (1–1,000
characters), with optional `Rappel personnalisé`, `Réunion du staff`, `Échéance`,
`Événement HRP`, or `Événement RP` category labels. Stored category and delivery
values remain unchanged, so existing reminders need no database migration.

Reminders are stored in MySQL and checked every 15 seconds while the bot is
online. Overdue reminders are delivered after a restart. The worker rechecks
membership and destination permissions before sending, uses atomic claims to
coordinate workers, and recovers interrupted claims after five minutes.
Transient failures retry up to five times with backoff; permanent failures
appear in `/reminder list`, with an attempted DM notification to the creator.
Edit a failed reminder with a new future schedule to retry it. Sent and failed
records are removed after 30 days. As with other Discord API sends, a crash
after Discord accepts the message but before MySQL records success can cause
a duplicate on recovery. Recurring reminders are a future extension.

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

The general log channel configured with `/setlogs` also receives message edits,
single deletions, and bulk deletions from allowed guilds, including threads.
Records show the message author (not an inferred deleting moderator), source
channel, message ID, creation time, event time, available content, and attachment
names and URLs. Edits show before/after versions and a link to the message.
Attachment-only changes are recorded; link previews and pin updates are ignored.
Long records include a UTF-8 text file with the unabridged content. Bulk deletions
produce one summary and a text transcript. The bot needs View Channel, Send
Messages, Embed Links, and Attach Files in the destination. If attaching a file is
forbidden, the bot sends the summary with an explicit notice instead. Mentions in
logs never ping users or roles. The bot's own cached messages are excluded to
avoid logging its own log deletions.

Previous content is resolved from Discord's cache and encrypted MySQL history,
so tracked messages survive bot restarts. Collection starts when `/setlogs` is
configured, unless an administrator disables it. The bot's own messages and DMs
are excluded. Content that was never received/imported or has expired is marked
unavailable; Discord cannot supply a deleted message or an earlier edit version.
Updates use the Gateway event's content rather than fetching a potentially newer
version. Attachment URLs may expire; attachment binaries are not downloaded or
reuploaded. General logs must be restricted to the intended moderation team.

### Persistent message history

Defaults are **30 days, 5,000 retained versions per guild, and 10 versions per
message**, whichever limit is reached first. Administrators can reduce retention
to 1–30 days and set a guild cap of 100–20,000 versions. New writes evict the
oldest versions immediately when a capacity limit is reached. Expired content
is excluded from queries immediately and physically removed every 15 minutes
while the bot is online, including at startup. Removed/disallowed guilds are
also cleared during maintenance. Each encrypted snapshot has a 64 KiB plaintext
size bound; oversized snapshots are rejected without storing a partial body.

| Command | Description |
| --- | --- |
| `/messagehistory recent [channel] [user] [event]` | Private, paginated view of edits/deletions; optional author and event filters |
| `/messagehistory view <message_id> [channel]` | Browse retained versions and retrieve the full text; accepts an ID or message link |
| `/messagehistory status` | Show retention, usage, capacity, and collection status |
| `/messagehistory import [channel] [limit]` | Import up to 1,000 recent existing messages from one channel — admin |
| `/messagehistory configure [enabled] [retention_days] [max_entries] [confirm]` | Change retention/capacity; disabling erases stored history — admin |
| `/messagehistory purge <channel> [message_id] [confirm]` | Erase retained versions for one channel or message — admin |

All message-history commands require **Manage Server** or **Administrator**,
plus View Channel and Read Message History in the source channel for both
the caller and bot. Private threads additionally require membership or Manage
Threads. Source access is checked again on every button interaction. Pages are
loaded afresh so purged/expired records cannot be downloaded from cached views;
responses are ephemeral and views expire after two minutes. Specify the source
channel when running the command in a different channel. No decrypted message
body is written to console logs or the administrative audit trail.

Discord command visibility defaults to **Manage Server**, matching the bot's
administrative runtime checks and help visibility. **Manage Messages alone does
not grant access** to any history command, including consultation. No role name
or role ID is required. `/help` lists all six commands under **Admin · Suivi des
messages** for members with Manage Server or Administrator. Every administrative
help page rechecks these permissions when selected. Command permission changes
take effect after deployment and the bot's normal guild-command synchronization.

The public Economy help page documents `/pay <user> <amount> <reason>` for player
transfers. The Roleplay page also references `/pay` for NAX transfers between
characters; both use the existing currency-selection flow.

Import is explicit, newest-first, bounded to the retention window, and limited
to one operation per guild. It scans 200 messages by default, up to 1,000, with
a two-minute deadline and a one-minute command cooldown. Existing tracked
messages are never overwritten, and an import cannot resurrect data after a
purge or configuration change. Imported snapshots expire relative to their
original creation time; importing does not renew retention. Lowering retention
or capacity applies immediately; increasing them does not extend existing
expiry dates. Disabling or purging requires `confirm:true`.

Content, usernames, and attachment names/URLs are authenticated-encrypted with
[Fernet](https://cryptography.io/en/stable/fernet/). Guild/channel/message/author
IDs and event/expiry metadata remain queryable in MySQL and are authenticated
inside the encrypted payload to detect ciphertext moved across messages or guilds.
The encryption key is independent of the Discord token and database credentials.
Compose creates it automatically in the **`message_history_keys`** volume at
`/app/history-keys/content.key`, owned by the bot user with mode `0600`. This volume
survives container recreation; a rebuild is required to add it to an existing
installation. For a direct Python run, the default path is
`history-keys/content.key`. `MESSAGE_HISTORY_KEY_FILE` can select a dedicated
owner-only secret file, or `MESSAGE_HISTORY_KEY` can provide a Fernet key through
the deployment's secret environment. Key files are excluded from Git and Docker
build contexts. Startup refuses a missing/wrong key when encrypted data exists.

Back up the key separately in protected offline storage and restore it alongside
the database; database backups alone cannot decrypt this history. Losing the
key makes the stored contents unreadable. Do not delete the key volume when
recreating the stack. Database purges cannot erase older SQL backups: encrypted
copies age out under `BACKUP_RETENTION_DAYS` (14 days by default). Discord log
messages, transcripts, and downloaded exports follow their own retention and
remain until removed by administrators; the database cleaner does not remove them.

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
| `/rphealth` | Check RP image references — admin |
| `/rpmaintenance <enabled>` | Pause or resume RP webhook messages — admin |
| `/setrpchannel <channel>` | Configure the RP announcement channel — admin |
| `/addnax <user> <amount>` | Add Nax — admin |
| `/removenax <user> <amount>` | Remove Nax — admin |

Dice rolls support 200 base dice per group, up to 20 repeated sets and four
semicolon-separated expressions. A shared budget of 10,000 actual random draws
per command includes every reroll and explosion, across all groups, sets, and
aliases. Exceeding that budget returns an explicit error instead of a partial
result. Fate, Warhammer, Godbound, and Wrath & Glory use the same group limit.
Expressions are limited to 1,000 characters, numeric literals to nine digits,
and dice to 1,000,000 sides. Excess sets and expressions are rejected explicitly.

Expressions are parsed completely before rolling. Unknown text, duplicate or
conflicting modifiers, and division by zero return clear errors. Use `! text`
for comments. Arithmetic supports chained `+ - * /`, parentheses, unary signs,
and normal multiplication/division precedence. Calculations remain exact:
terminating fractions are displayed as decimals when short, otherwise as exact
fractions. Series repeat the complete expression or alias, so `2 1d1+1d20` rolls two
independent pairs of dice. Success-counting pools cannot be mixed with raw
dice sums in one calculation; use separate semicolon-delimited rolls instead.
Fate participates in exact arithmetic and keep/drop selection. Numeric aliases
such as `ed7`, `sr3`, and `attack+5` can appear inside arithmetic expressions.
Examples include `ed7+2`, `(ed18+2)*3`, and `4df+1`. Display options apply to all
game aliases, including `4df s` and `age nr`; series also support `2 4df` and
`2 age s`. Repeats cannot be nested, and all draws share the command budget.
Impossible keep/drop counts are rejected before rolling when the pool size is
known, or checked against the actual pool after explosions. At least one die
must remain after a drop operation.

Infinite reroll/explosion conditions that cannot terminate are rejected before
any draw. Reaching a chain cap cancels the command with an explicit explanation
rather than returning an incomplete value. Reroll rules also apply to bonus
explosion dice. Each retained/dropped die is displayed once; an explosion count
is shown separately. Commands containing only invalid expressions are private.
The optional CoD suffix controls its success threshold (8 by default); Earthdawn
steps outside 1–50 and unsupported suffixes are rejected instead of ignored.

When full results exceed the embed description limit, `/roll` sends a compact
summary and one UTF-8 text attachment containing the exact original results;
creating the summary never rerolls the dice. Private rolls keep both the summary
and attachment ephemeral. Short rolls remain a single embed. Each member can
invoke `/roll` five times per ten seconds per guild. `/roll help` describes the
roll limits and long-output behavior in French.
The public `/help` dropdown has a dedicated **Dés** category showing the same
page as `/roll help`; `/roll` is no longer listed under Roleplay.

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

To run the optional reminder MySQL integration test, start a disposable
MySQL 8 instance with the `reminder_test` database and empty root password,
bound only to localhost, then run:

```bash
REMINDER_TEST_DB_PORT=3307 python3 -m pytest -q tests/test_reminder_storage.py
```

The test initializes the schema, replays startup, and modifies data only in
`reminder_test`; it ignores the application's database configuration.

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

## Legal pages

Before submitting the application for Discord verification, publish the static
pages in `docs/` over HTTPS (for example with GitHub Pages). Review the owner,
contact email, date, and retention period in `docs/privacy.html` and
`docs/terms.html`. Then enter the public URLs in the
Discord Developer Portal under **General Information**:

```text
https://minamix-project.github.io/minamix_bot/privacy.html
https://minamix-project.github.io/minamix_bot/terms.html
```
