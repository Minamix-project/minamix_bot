# MinamixBot

A Discord bot with an economy system, shop, moderation tools, ...

## Requirements

- Docker & Docker Compose
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- **Privileged Gateway Intents** enabled in the portal: `Message Content Intent` and `Server Members Intent`

## Setup

1. Clone the repo and copy the env file:

   ```bash
   cp .env.example .env
   ```

2. Fill in your `.env`:

   ```env
   DISCORD_TOKEN=your_token_here
   DB_HOST=db
   DB_USER=minamix
   DB_PASSWORD=minamix
   DB_NAME=minamix
   DB_PORT=3306
   DB_POOL_MIN_SIZE=1
   DB_POOL_MAX_SIZE=10
   DB_POOL_RECYCLE_SECONDS=1800
   ```

3. Start the bot:

   ```bash
   make deploy
   ```

MySQL access uses an asynchronous connection pool. These pool settings are
optional and already use the displayed values by default.
The database is initialized automatically on first start.

## Commands

### Economy

| Command | Description |
| --- | --- |
| `/balance` | Check your balance |
| `/work` | Earn coins (1 week cooldown) |
| `/shop` | View available roles in the shop |
| `/buy [number]` | Buy a role (dropdown if no number given) |
| `/leaderboard` | Top 10 richest users |
| `/discoveries` | View your secret discoveries |

### Admin

| Command | Description |
| --- | --- |
| `/addmoney <user> <amount>` | Add coins to a user |
| `/removemoney <user> <amount>` | Remove coins from a user |
| `/additem <role> <price> <name> [exclusive] [description]` | Add a role to the shop |
| `/edititem <number> [price] [name] [description] [exclusive]` | Edit a shop item |
| `/removeitem <number>` | Remove a shop item |
| `/resetbalances` | Reset all balances to zero (triple confirmation) |

### Moderation

| Command | Description |
| --- | --- |
| `/setlogs <channel>` | Set the logs channel |
| `/addantispam <channel>` | Add an anti-spam channel (instant ban) |
| `/removeantispam <channel>` | Remove a channel from anti-spam |
| `/listantispam` | List active anti-spam channels |

## Deployment

```bash
make deploy    # git pull + rebuild + restart bot only (DB untouched)
make restart   # restart bot container without rebuilding
make logs      # follow live logs
make status    # show container status
```

## Project Structure

```text
src/
  bot.py              # Bot entry point
  config.py           # Guild IDs whitelist
  commands/           # Slash commands
    economie/
    moderation/
  events/             # Event listeners (messages, antispam)
  utils/              # Shared utilities (format, embed, shop, ...)
  model/              # SQL table definitions (auto-loaded on start)
  assets/             # Static files
```
