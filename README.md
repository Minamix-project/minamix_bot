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
| `/reminder` | Open the private reminder manager; all actions use buttons and menus |

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

The single `/reminder` command has no parameters or subcommands. Its name
remains in English; all user-facing descriptions, controls, forms and errors
are in French. Existing scheduled reminders survive upgrade with their text,
destination, mentions, due time, delivery status and
recovery lease unchanged. Migration `0022_reminder_manager` assigns personal
numbers in creation order per member and server, while retaining stable internal
IDs. Previously displayed global numbers are replaced by those personal numbers.
No data deletion or manual database reset is needed.

Open `/reminder` and press **Créer un rappel** for the private five-step assistant:
message, date, destination, member mentions, and a final review. Each step allows
back navigation; nothing is scheduled until **Programmer le rappel**. The review
also has direct field-edit buttons. Quick dates include ten minutes, one hour
and tomorrow at 18:00. Channel and member selection use native Discord menus;
up to ten additional members can be selected, with separate controls for the
creator's mention and clearing mentions. DM delivery skips the member step and
clears additional recipients.

`/reminder` opens the private manager, including empty states. Select a
reminder by its text, personal number, date and destination to see its full
card. Buttons allow editing, ten-minute/hour postponement, deletion with
confirmation, and returning to the list. **À venir**, **Échecs**, and **Envoyés
récemment** tabs, pagination, refresh, timezone preferences and personal reset
are available. History from an earlier reset cycle is labelled separately.
A failed or overdue reminder opens at the date step instead of requiring the
user to discover why an unchanged past date fails.

**Réinitialiser mes rappels** opens a private confirmation. Confirming cancels
the member's pending and failed reminders in the current server and restarts
the next visible number at #1. Other members, other servers, sent
history and the saved timezone are retained. Reset is refused while a reminder
is being sent or when the confirmation's reminder set has changed. Creation,
number allocation and reset are transactional. Generations invalidate creation
drafts and old snooze buttons after reset; stable IDs and revision checks prevent
old controls from targeting a different reminder with a reused visible number.

Dates accept `2h`, `1j 30m`, `1sem`, `15/09/2027 20:00`, `2027-09-15 20:00`,
`demain 18:00`, `aujourd'hui 18:00`, and `18:00` for today. English duration
units and day names remain accepted. A bare time already past offers an explicit
choice of tomorrow at that time; it is never silently shifted. Other past dates,
invalid or ambiguous/nonexistent local times, and schedules over five years away
are rejected. The member can save a timezone per server from common French-labelled
choices or an IANA name; the default remains Europe/Brussels. Existing schedules
retain their due time. Discord timestamps display in the reader's local timezone.

The destination selector offers private messages, the current channel, or a
native text-channel menu. The creator must see and send in
the destination; the bot also needs Embed Links. Threads remain unsupported.
Mentions use a native member selector and dedicated buttons to mention the
creator or clear all mentions. No user IDs or text separators are needed.
All selected members must see the channel; roles,
@everyone and unselected users cannot be pinged. Creator-only delivered-message
buttons **Reporter de 10 min / 1 heure** work in DMs and server channels, including
after bot restart. Snoozing a delivered reminder creates one new personal reminder;
concurrent/repeated clicks cannot create duplicate reports. Editing a pending
reminder postpones that reminder in place. Permissions are checked again on save,
snooze and delivery. Management sessions expire after five minutes with instructions
to reopen the manager.

MySQL reminders are polled every 15 seconds while online. At most three delivery
tasks run at once; only free slots are claimed, and one slow send cannot hold up
other slots or later polls. Shutdown cancels and awaits active sends, leaving
interrupted leases recoverable after five minutes. Failed transient sends retry
up to five times with backoff; terminal failures appear in the manager and trigger
an attempted private notification identifying the originating server. Sent and
failed records are retained for 30 days. A crash after Discord accepts a message
but before MySQL records success can still cause a duplicate on recovery.
Recurring reminders are not introduced.

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
| `/devlog [version] [preview]` | Publish or preview releases and catch up missing versions — admin |
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

The first publication loads the selected release's entire `major.minor` series
up to that version. For example, publishing `v1.8.3` includes available releases
`v1.8.0` through `v1.8.3`. Later publications also catch up releases after the
previously tracked series. If `v1.9.0` was published and the latest release is
`v1.11.0`, one new message contains `v1.10.0`, its patches, and `v1.11.0`, in
ascending version order. If `v1.11.0` was already published alone, its existing
message is updated to include the missing releases above it. Patches for an
already tracked series stay in that series' existing message; grouped catch-up
messages also remain grouped when later patches are published.

Major versions use `kchoc`, minor versions use `kgun`, and patches use `-`.
Actual version numbers determine the category, rather
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

At Discord's 2,000-character limit, a batch continues in additional messages,
which are subsequently edited too. Each batch is limited to 10 messages, and
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
**Gérer les panneaux**. Use **Gérer les catégories** or `/ticket categories` for
shared support-category settings. The panel creation/editor wizard has five steps:

1. **Nom et message**: a modal sets the manager name (1–80 characters), public
   title (up to 256 characters), and multiline text (up to 4,000 characters).
   Blank title/text fields use the default panel message.
2. **Catégorie Discord des tickets**: select the category for private ticket channels.
3. **Salon des transcripts**: optionally select a private text channel for the
   transcript files, or choose **Sans salon de transcripts**. Database storage
   remains enabled regardless of this choice.
4. **Salon des logs de tickets**: optionally select a text channel for ticket
   action summaries, or choose **Sans envoi de logs**.
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
The migration preserves existing published panels, transcript destinations,
message IDs and ticket numbers.

Public panels offer Partnerships (🔗), Character validation (✅), Complaints (⛔),
Help (🆘), Other (🤔) and Bot (🤖) categories, with French labels and descriptions.
Existing public menus are refreshed on startup while retaining their custom
embeds. Historical ticket categories remain readable in information, logs and
transcripts. Their menus work after restarts and clear after every
selection, including rejected requests, so members can select the same category
again. Each panel footer shows the bot's name and avatar, including its default avatar.

**Transcripts, ticket logs and general logs have separate configuration.** The
private transcript channel and optional ticket action log channel are selected
independently per panel in the wizard. Ticket action summaries only use their
configured destination, with no fallback to `/setlogs`; they do not contain
transcript files or message bodies. Without a ticket log destination, no action
summary is sent to Discord, while the database audit history remains available.
Existing panels start without a ticket log channel; edit them to configure one.
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
French embed displays the category emoji and tailored opening guidance, explains
that support will reply shortly and offers a persistent
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

Each member can have one open ticket per help category per server. For example,
one Bot ticket and one Complaints ticket may remain open together, but two Bot
tickets are rejected even when opened through different panels or commands.
New channels use explicit permissions for the creator, all configured support roles and the bot; other
category permissions are not copied. Discord administrators can always access
channels. Support roles belong to the selected help category, independently of
which panel created the ticket. The six default categories are persisted per
guild with **no support roles**; administrators configure them themselves with
`/ticket categories`. Panels no longer store or edit support roles. With no
roles configured, a new ticket is accessible to its creator, the bot and Discord
administrators.

The private category editor changes the name (100 characters), Unicode or
accessible custom emoji, menu description (100 characters), opening message
(2,000 characters), and zero to ten dedicated support roles. Unsaved drafts are
discarded when switching categories. Saved edits use version checks to prevent
concurrent overwrites. `/ticket create` autocompletion uses the current names.
Category keys remain stable when renamed, so the per-category ticket limit is
preserved.

**Prise en charge** is enabled by default for every existing and new category.
The category editor can toggle it before saving. Members holding one of that
category's support roles, or members with Administrator or Manage Server, can
use **Prendre en charge** or `/ticket claim` in an open ticket.
Only one person can claim a ticket; concurrent requests are serialized and
guarded in MySQL. Claiming does not modify channel access or other staff powers.

The opening embed shows the responsible member and claim time. An open,
unassigned ticket with claiming enabled ends in a red dot: `ticket-0001-🔴`.
Claiming replaces it with the responsible member's marker and name, for example
`ticket-0001-🟢-alice`. Support staff can set their personal Unicode marker with
`/ticket emoji emoji:🎯`; `/ticket emoji` without an argument restores the green
dot. The preference is saved per server and immediately updates their assigned
tickets, always retaining the member's name after the marker.

The responsible member or an administrator (Administrator or Manage Server) can
use **Libérer le ticket** or `/ticket release`, including after a restart.
Release restores the base name and adds the red dot if the ticket is open and
claiming remains enabled. Renaming retains the appropriate marker and updates
the saved base name. Claim history includes both the releasing actor and former
responsible member in action logs, the administrative audit and transcripts.

Disabling claiming prevents new claims and hides the claim button. An existing
responsible member keeps their assignment and can still release it while they
have access, including in a closed ticket. Closing and reopening keep assignment
history and ownership. Previously created tickets receive the controls during
startup category synchronization. If an opening message was deleted, an explicit
claim or release recreates its information and controls without pinging members.

Use **Créer une catégorie** to draft a new category with its own generated key,
texts, emoji and optional roles, then press **Créer** to publish it. Up to 25
categories can be active per guild. The limit is checked again when saving.
Choose an existing category and press **Supprimer** for a private confirmation.
Confirming removes it from every public menu and from `/ticket create`, while
existing tickets retain their category name, permissions, transcripts and normal
management commands. Deleted categories stay archived internally, so defaults
are not recreated on restart and names remain available in historical logs.
If every category is deleted, public menus are disabled until another is created.

Saving a category updates every public panel menu and all its existing ticket
channels, including tickets whose panel was deleted. It changes channel topics,
opening embeds and support permissions while preserving ticket numbers and
explicit creator/guest access. Closed tickets remain private and writable by support and administration;
their saved reopening permissions receive the same role changes. Initial
messages are tracked by ID; older ones are recovered among the first 50 messages
when possible. Deleted opening messages are left deleted. Historical transcript
files remain unchanged, while new exports and action logs use the current name.

The bot checks affected channels before editing and restores completed Discord
changes if persistence fails. Deleted channels are skipped. Startup synchronizes
pending category versions and refreshes public menus. Transcript and ticket log
destinations retain their creation-time values. Existing role snapshots are
replaced by category roles during synchronization; former panel roles are not
copied into the empty category defaults.

Use `/ticket create reason:<choice> [user] [panel]` to open a ticket directly.
The required `reason` dropdown contains the same six French categories as the
public panel. `user` accepts a server member and is restricted to Administrator
or Manage Server; the selected member owns the ticket, receives its welcome
mention and close button, and is subject to the category limit. The administrator
who runs the command is recorded as the actor. Bots and foreign members are
rejected. Without `user`, the requesting member owns the ticket.

The optional `panel` autocomplete lists only panels in channels the requesting
member can see. If omitted, the command uses the only available panel in the
current channel, or the only available panel in the server. Ambiguous choices
require selecting `panel`. Each ticket uses that panel's channel category,
transcripts and ticket log destination; support roles come from the chosen help
category.

| Command | Access and behavior |
| --- | --- |
| `/ticket categories` | Administration; edit shared categories and synchronize their existing tickets |
| `/ticket create <reason> [user] [panel]` | Everyone; create directly, with `user` restricted to administration |
| `/ticket add <user>` | Support role or administration; grant access to another member |
| `/ticket remove <user>` | Support role or administration; deny that member access |
| `/ticket rename <name>` | Support role or administration; rename the current ticket |
| `/ticket close <reason>` | Creator or support; remove participant access and save a transcript |
| `/ticket reopen` | Support role or administration; restore previous access permissions |
| `/ticket delete` | Support role or administration; confirm channel deletion while retaining archives |
| `/ticket claim` | Category support role or administration; exclusively claim an open ticket without changing access |
| `/ticket release` | Current responsible member or administration; release the ticket |
| `/ticket emoji [emoji]` | Support role or administration; set a personal Unicode claim marker, or reset to green |
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

Closing retains the channel for staff review, removes visibility for ordinary
creators and invited members, and saves their previous permissions. Members with
category support roles or administration permissions retain reading, writing and
application command access, including when they created the ticket themselves.
Closed channel names end in `-🔒`, after the responsible member's marker and name
if assigned. The opening embed also indicates closure and offers **Rouvrir le
ticket** and **Supprimer le ticket** buttons. Reopening removes the lock and
restores the usual availability or assignment marker.

Roles with Administrator or Manage Server receive explicit access on new and
existing tickets without being added to category support roles. These grants
and the saved reopening permissions are synchronized at startup and when the
roles gain or lose those permissions; revoked managed role grants are removed.
This also covers tickets whose help category was deleted. The bot saves the transcript and optionally
uploads it to the private transcript channel. If transcript delivery fails, the saved transcript
remains available through `transcript`. Reopening by staff restores the saved permissions for the creator and previously added members;
a second open ticket for the same creator and help category prevents reopening.
Tickets in other help categories do not prevent reopening. MySQL transactions,
a per-server lock and a unique constraint prevent duplicate opens. On ordinary
Discord or database failures, completed channel changes are undone. Discord and
MySQL cannot commit atomically: a process termination between their operations
can require manual reconciliation. A deleted channel can be reconciled without
inventing a transcript; previously stored exports remain in the database.

Discord requests reject rate-limit waits longer than 30 seconds. Ticket channel
edits remember Discord's retry deadline and refuse repeated requests locally
until that deadline expires. The response gives the affected member the retry
delay, without creating a technical error alert. Ticket transactions have a
45-second deadline and release their guild lock on timeout or cancellation.
Compensating Discord calls are also bounded so recovery cannot wait indefinitely.

Background synchronization processes and commits one ticket at a time, skips
rate-limited channels, and retries unfinished work every minute while the bot is
ready. Reconnects share one worker, which is cancelled when the cog is unloaded.
Names, permissions and topics are combined into one channel edit when needed;
unchanged fields and already applied names are not sent again. This prevents a
long channel cooldown from blocking synchronization of the other tickets.

Transcripts include available messages in chronological order, author/message
IDs, timestamps, replies, embed text, attachment links, ticket metadata and action
history. They do not include deleted messages, past edits, thread histories or
attachment binaries; Discord attachment URLs may expire. Both open and closed
tickets create a fresh snapshot when exported, including staff messages written
after closure. Previous snapshots remain archived. Exports are capped
at 20,000 messages and the smaller of 8 MiB or the server upload limit. Exceeding
a limit or failing to read history aborts closure and restores permissions, with
no silently truncated transcript. Records and transcripts remain in MySQL until
removed by an administrator with `/ticket purge` or through database maintenance and are covered by the
normal database backups. No administrative web interface is introduced.

`/ticket delete` and **Supprimer le ticket** use the same private, single-use
confirmation, expiring after 60 seconds. Only category support staff or members
with Administrator or Manage Server may confirm; authority and ticket identity
are checked again when executing. Open tickets are first closed and archived.
A current transcript is committed before deleting the Discord channel and is
sent to the configured transcript destination when available. A failed archive
prevents deletion; a Discord deletion failure leaves the ticket closed and
retryable. The ticket record, events, staff history, transcripts and sequence are
retained; a successful deletion is recorded in ticket logs and the audit journal.
Deleting a single ticket never resets numbering. A database failure after Discord
deletes the channel can leave its record closed, but the committed archive is
preserved. Channels hosting panels or receiving transcripts or ticket logs must
be moved out of those configurations before deletion. Full archive erasure and
numbering reset remain restricted to `/ticket purge`.


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
