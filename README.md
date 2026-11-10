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

## Rotating Discord presence

The bot rotates its Discord activity every five minutes, starting when it is ready:

- Watching: `Les bots prendre le pouvoir`
- Listening: `Les plaintes des utilisateurs`
- Playing: `La version <version> de <bot name>`
- Competing: `La lutte pour l'égalité entre bots et humains`

The playing activity uses the running `BOT_VERSION` and the current Discord bot
name. Missing/development version metadata displays `de développement`. The worker
stays single across reconnects, retries failed updates without skipping an activity,
and is canceled when the cog or bot shuts down.

## Permissions

Administrative commands require **Manage Server** or **Administrator**. RP
management commands use the same **Manage Server** or **Administrator**
permission. These rules are enforced both by Discord command visibility and by
the bot at runtime.

## Delete messages with a reaction

On allowed servers, user `840870799064956930` can react with the standard ❌
(`:x:`) emoji to delete the reacted-to message, regardless of its author. Other
users retain only the existing ability to delete their own tracked RP messages.
Both actions use a single reaction listener, so the same event is not handled
by competing deletion features. Other emojis are ignored; direct messages and
unauthorized servers are excluded. Raw reaction events also support messages
outside the bot's cache. The bot needs access to the channel and Manage Messages
to delete other users' messages. Normal message-deletion logs/history still apply.
Already deleted messages are ignored; Discord permission/API failures retain RP
ownership for retries and use the configured technical error reporting.

## Commands

### General and absence

| Command | Description |
| --- | --- |
| `/help` | Show the interactive help |
| `/status` | Show bot status, main-branch repository statistics and the latest stable main release |
| `/changelog` | Show recent GitHub releases |
| `/afk` | Set your absence status |
| `/back` | Clear your absence status |
| `/absents` | List absent members — admin |
| `/activity <user>` | View a member's activity — admin |
| `/reminder create <when> <text> [...]` | Schedule a reminder, delivered by DM by default |
| `/reminder list` | List your pending reminders and delivery failures in this server |
| `/reminder edit <reminder_id> [...]` | Update one of your pending or failed reminders |
| `/reminder delete <reminder_id>` | Delete one of your pending or failed reminders |

### Repository statistics in status

`/status` displays code lines, files, commits, detected languages, and the latest
published stable release targeting `main`, alongside the normal latency, uptime,
server and member counts. The file count includes every regular file in the
main-branch archive. Lines count nonblank lines in recognized source/configuration
files (comments included); Markdown documentation and binary assets are excluded
from line/language counts. Python, SQL, HTML, YAML and other recognized source or
configuration formats are listed by their share of counted lines.

Counts are pinned to one main commit: they use GitHub's public API and an in-memory
source archive, so the production container needs neither Git nor a `.git` directory.
No source files are extracted. Downloads, archive size, file count and request time
are bounded. Results are cached for ten minutes; concurrent requests share one
refresh. On a temporary GitHub failure, cached values are marked as stale, or the
repository fields show as unavailable while basic bot status remains available.
The latest release is a published main release, not necessarily the version running
in the current container. GitHub request failures are retried after two minutes.

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
| `/setdevlog <channel>` | Configure the bot's devlog channel — admin |
| `/devlog [version] [preview]` | Publish or preview a GitHub release series — admin |
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
logs never ping users or roles. Messages from all bots, applications, and webhooks
(including RP proxies and the bot's own logs) are excluded from capture, imports,
edits, single deletions, and bulk-deletion summaries. Automated messages identified
in the cache or Gateway payload are rejected before any history database lookup.

Previous content is resolved from Discord's cache and encrypted MySQL history,
so tracked messages survive bot restarts. Collection starts when `/setlogs` is
configured, unless an administrator disables it. DMs are excluded. Content that
was never received/imported or has expired is marked
unavailable; Discord cannot supply a deleted message or an earlier edit version.
Events without an identifiable human origin are skipped: raw deletions contain
no author, so the bot needs its message cache or retained history to classify
them. Origin metadata is encrypted with each new snapshot and survives restarts;
older snapshots remain readable, but require a cached message or a subsequent
edit with author information before their origin can be established. Existing
history and previously sent Discord logs are not retroactively erased.
Updates use the Gateway event's content rather than fetching a potentially newer
version. Attachment URLs may expire; attachment binaries are not downloaded or
reuploaded. General logs must be restricted to the intended moderation team.

### Bot devlog

Configure a text or announcement channel with `/setdevlog <channel>`, then use
`/devlog` to publish the latest stable GitHub release from this repository.
`/devlog version:v1.8.3` selects a specific release; `preview:True` displays a
private preview without changing the public channel. Both commands require
Administrator or Manage Server, and appear under **Admin · Configuration** in
`/help`. `/config` also displays the devlog channel.

The command loads the selected release's entire `major.minor` series up to that
version. For example, publishing `v1.8.3` includes available releases `v1.8.0`
through `v1.8.3`. A major version starts its own message with `kchoc`; a minor
version starts another with `kgun`; patches use `-` and are appended to their
major or minor message. Thus `v2.0.1` is added below `v2.0.0`, while `v2.1.0`
starts another message. Actual version numbers determine the category, rather
than PR title prefixes. The bot uses available custom emojis named `kchoc` and
`kgun`, falling back to 🚀 and 🎯. External custom emojis additionally require
Use External Emojis in the destination.

Each entry displays a real mention of the bot, release version, and PR title/link extracted
from the release notes generated by the release workflow. Other release notes
fall back to the release title/link. Announcements suppress link previews and
allow mentions of the bot itself only; role, everyone, and other user mentions
remain disabled. Private previews disable all mentions. The bot needs View
Channel, Send Messages, and Read Message History.

Published entries and Discord message IDs are saved in MySQL. Repeating a
publication updates the existing messages after restarts, keeps previously
published newer patches, and sends nothing when already up to date. Publications
and channel changes are serialized per server. Deleted announcement messages
are recreated; changing channels leaves the old announcements in place and
starts independent tracking in the new channel. A retry can recover matching
bot announcements among the last 100 messages if Discord accepted a send before
its database record was saved. A crash followed by more than 100 newer channel
messages can prevent this recovery. Only bot-authored announcements can be
updated; pre-existing messages posted manually by other users cannot be adopted.

At Discord's 2,000-character limit, the series continues in additional messages,
which are subsequently edited too. Each series is limited to 10 messages, and
GitHub discovery scans at most 1,000 releases. Requests that cannot establish the
complete series within this bound fail without publishing a partial list. There
is no automatic publication on startup or merge: an administrator runs `/devlog`.

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

The `backup` service creates periodic SQL dumps and removes completed dumps older
than `BACKUP_RETENTION_DAYS` at each successful backup. The interval defaults to
six hours and retention to fourteen days; `.env` may override these values.
Rotation uses minute-level ages rather than rounded whole days, and is restricted
to dump filenames for the configured database. Failed dumps remove their temporary
file; subsequent successful runs remove leftover empty `.sql.tmp` files older than
one hour. Recent temporary files and nonempty partial dumps are retained. Valid
backups are not rotated away if the new dump fails. Dumps are created with
owner-only permissions. The
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

### Integrated support tickets

Aurum provides persistent ticket panels with French labels and responses. Code
and command names are in English. Open the private setup interface with no parameters:

```text
/ticket panel
```

Manage Server or Administrator is required. Choose **Créer un panneau** or
**Gérer les panneaux**. The creation/editor wizard has five steps:

1. **Nom et message**: a modal sets the manager name (1–80 characters), public
   title (up to 256 characters), and multiline text (up to 4,000 characters).
   Blank title/text fields use the default panel message.
2. **Rôles de support**: select 1–10 dedicated roles through Discord's role picker.
3. **Catégorie des tickets**: select the category for private ticket channels.
4. **Salon des transcripts**: optionally select a private text channel for the
   transcript files, or choose **Sans salon de transcripts**. Database storage
   remains enabled regardless of this choice.
5. **Envoi du panneau**: select the destination text channel, then press
   **Enregistrer et envoyer**.

Each step has **Retour** and **Enregistrer et continuer**. Navigation retains the
current draft; changes are saved and published only on the final step. Canceling,
leaving the wizard, or its ten-minute timeout discards the draft. Each editor is
restricted to its requesting administrator and rechecks permissions on interactions
and modal submissions. A concurrently edited panel must be reopened before saving.

The manager lists panels by ID and name, paginated in groups of 25. Each panel can
be edited, sent/moved, or removed independently. Removal requires confirmation,
disables that panel's public menu and retains its existing tickets. Moving a panel
disables only its old message. Multiple panels can also share the same text channel.
The migration preserves existing published panels, roles, transcript destinations,
message IDs and ticket numbers.

Public panels offer General support, RP issue, Shop, Report, Application and Staff
request categories in French. Their menus work after restarts and clear after every
selection, including rejected requests, so members can select the same category
again. Each panel footer shows the bot's name and avatar, including its default avatar.

**Transcripts and general logs are separate.** The private transcript channel is
selected per panel in the wizard. Ticket action summaries use the existing general
log destination configured with `/setlogs`; they do not contain transcript files or
message bodies. Setting a transcript destination does not change the general logs.
Ticket journals use the same moderation layout: action icon and color, named fields
for the channel, ticket, category, creator and actor, a timestamp, the creator's
avatar and the bot footer. Member changes also identify the affected member.
Transcript notifications follow the same layout in their private destination.
Expected access/validation refusals produce one private explanation and no technical
alert. A locally handled ticket error is not reported again by the global command
handler; unexpected failures report their underlying type and full command name
such as `/ticket add`.

The bot needs Manage Channels and Manage Permissions in the ticket category, plus
View Channel, Send Messages, Read Message History, Embed Links and Attach Files in
the relevant destinations. Enable the privileged Message Content and Server Members
intents. `@everyone` and integration-managed roles cannot be support roles.

Opening a ticket mentions only its creator with a French welcome message. A
French embed explains that support will reply shortly and offers a persistent
**Fermer le ticket** button, with the bot's name and avatar in its footer. Only
the ticket creator can use that button, including after a bot restart. It opens
a private **Es-tu sûr de vouloir fermer ce ticket ?** confirmation with a red
**Fermer** button and **Annuler**. The confirmation expires after 60 seconds and
can only be used once. Confirming rechecks the creator and ticket before using
the normal transcript/archive flow; canceling leaves the ticket unchanged.
Support staff use `/ticket close <reason>` instead of the button.

Ticket numbers are independent per server and channel names use `ticket-0001`,
`ticket-0002`, etc. Numbers longer than four digits are kept in full. Existing
numbers are preserved by the migration; default channel names are padded on
startup, while custom names remain unchanged.

Each member can have one open ticket per server. New channels use explicit
permissions for the creator, all configured support roles and the bot; other
category permissions are not copied. Discord administrators can always access
channels. Existing tickets retain the support roles and transcript destination configured
when they were created. Category/role removal requires panel reconfiguration.

| Command | Access and behavior |
| --- | --- |
| `/ticket add <user>` | Support role or administration; grant access to another member |
| `/ticket remove <user>` | Support role or administration; deny that member access |
| `/ticket rename <name>` | Support role or administration; rename the current ticket |
| `/ticket close <reason>` | Creator or support; remove participant access and save a transcript |
| `/ticket reopen` | Support role or administration; restore previous access permissions |
| `/ticket transcript` | Creator while open, or support; private UTF-8 text file, saved in MySQL |
| `/ticket info` | Creator while open, or support; category, creator, dates, staff and closure details |
| `/ticket link <user>` | Support role or administration; associate a subject without granting access |
| `/ticket purge` | Administration; confirmation required; delete all ticket channels/data in this server and reset numbering |
| `/ticket reconcile <channel_id> <reason>` | Administration; close a record only after Discord confirms its channel was deleted |

All management replies are ephemeral and require visibility of the current
ticket. Invited members can participate but cannot manage or export it. The
creator and support access cannot be removed through these commands. The
configured support roles can manage tickets even without Manage Server.
`info` includes the linked subject for support staff; administrators additionally
see their warning count and guidance for `/warnings` and `/audit`. Ticket
mutations are recorded in the existing administrative audit log and in a detailed
ticket event history, which preserves previous close/reopen cycles. Use
`/audit commande:ticket` to filter these actions and `/config` to inspect the panels. Staff who
send messages or perform actions are recorded separately.

Closing retains the channel for staff review, removes visibility for the creator
and added members, saves their previous permissions, and makes the remaining staff
access read-only. Staff-role access and the bot's permissions are retained; Discord
administrators still bypass overwrites. The bot saves the transcript and optionally
uploads it to the private transcript channel. If transcript delivery fails, the saved transcript
remains available through `transcript`. Reopening by staff restores the saved permissions for the creator and previously added members;
a second open ticket for the same creator prevents reopening. MySQL transactions,
a per-server lock and a unique constraint prevent duplicate opens. On ordinary
Discord or database failures, completed channel changes are undone. Discord and
MySQL cannot commit atomically: a process termination between their operations
can require manual reconciliation. A deleted channel can be reconciled without
inventing a transcript; previously stored exports remain in the database.

Transcripts include available messages in chronological order, author/message
IDs, timestamps, replies, embed text, attachment links, ticket metadata and action
history. They do not include deleted messages, past edits, thread histories or
attachment binaries; Discord attachment URLs may expire. A closed ticket exports
its closing snapshot; an open ticket creates a fresh snapshot. Exports are capped
at 20,000 messages and the smaller of 8 MiB or the server upload limit. Exceeding
a limit or failing to read history aborts closure and restores permissions, with
no silently truncated transcript. Records and transcripts remain in MySQL until
removed by an administrator with `/ticket purge` or through database maintenance and are covered by the
normal database backups. No administrative web interface is introduced.


Run `/ticket purge` outside a ticket channel. Its private confirmation expires
after 60 seconds and is restricted to the requesting administrator. Permissions
are checked again on confirmation, and the confirmation can only be used once.
The preview itself does not delete anything. If the ticket list changes, a new
confirmation is required. Purge deletes open and closed ticket channels, ticket
metadata, staff participation, action history, database transcripts and retained
message history for those channels. The panels remain configured, and the next
ticket is `ticket-0001`. Other servers and unrelated message history are kept.
If any channel deletion fails, records and numbering are retained for a retry;
some channels may already have been deleted. A minimal purge audit record is kept.
Copies already sent to Discord logs, downloaded exports and existing SQL backups
are outside this database purge and follow their existing retention.
