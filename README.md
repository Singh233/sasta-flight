# SastaFlight ✈️

Daily flight price scanner Telegram bot. Scans Google Flights for the cheapest days to fly on your routes and sends you a daily summary.

**What it does:** Every morning (or whenever you choose), you get a Telegram message with the 5 cheapest days to fly in the next 30 days for each of your saved routes — with prices, airlines, and trends.

## Quick Start

### 1. Create a Telegram Bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the bot token

### 2. Get Your Chat ID

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. Copy the `Id` number

### 3. Deploy

#### Option A: Railway (Recommended)

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template)

1. Fork this repo
2. Go to [railway.com](https://railway.com) → New Project → Deploy from GitHub repo
3. Select your forked repo
4. Add environment variables:
   - `TELEGRAM_BOT_TOKEN` = your bot token
   - `TELEGRAM_CHAT_ID` = your chat ID
5. Railway will build and deploy automatically
6. Add a volume mounted at `/app/data` for persistent database storage

That's it. Your bot is running.

#### Option B: Docker Compose (Any VPS)

```bash
git clone https://github.com/yourusername/sasta-flight.git
cd sasta-flight
cp .env.example .env
# Edit .env with your bot token and chat ID
docker compose up -d
```

#### Option C: Run Locally

```bash
git clone https://github.com/yourusername/sasta-flight.git
cd sasta-flight
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your bot token and chat ID
python -m bot.main
```

## Usage

Once the bot is running, message it on Telegram:

```
/add ATQ BOM          Add a route (Amritsar → Mumbai)
/add DEL BLR          Add another route (Delhi → Bangalore)
/check                Scan all routes right now
/routes               List your saved routes
/remove 1             Remove route by ID
/time 07:30           Change daily scan time (default: 08:00 IST)
/history              See 7-day price trend
/pause                Pause daily updates
/resume               Resume daily updates
/help                 Show all commands
```

## Daily Message Example

```
✈️ ATQ → BOM | Next 30 Days
━━━━━━━━━━━━━━━━━━━━━━

🏆 Cheapest: Mar 18 (Tue) - ₹3,200
   IndiGo | 06:00 AM | 2h 45m | Nonstop

📊 Top 5 Cheapest Days:
 1. Mar 18 (Tue) - ₹3,200
 2. Mar 20 (Thu) - ₹3,450
 3. Mar 25 (Tue) - ₹3,500
 4. Mar 12 (Wed) - ₹3,800
 5. Mar 15 (Sat) - ₹4,100

📈 Avg: ₹5,200 | Low: ₹3,200 | High: ₹8,900

💡 Trend: Prices dropped 8% since yesterday
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | — | Your Telegram chat ID |
| `DAYS_TO_SCAN` | No | `30` | Number of days ahead to scan |
| `TOP_CHEAPEST` | No | `5` | How many cheapest days to show |
| `TIMEZONE` | No | `Asia/Kolkata` | Timezone for scheduling |
| `DB_PATH` | No | `data/flights.db` | SQLite database path |

## How It Works

- Uses [Fli](https://github.com/punitarani/fli) to query Google Flights' internal API
- Only 2 API calls per route per scan (one for date prices, one for flight details)
- Price history stored in SQLite for trend tracking
- If a scan fails, it retries once after 4 hours

## Tech Stack

- Python 3.12
- [Fli](https://github.com/punitarani/fli) — Google Flights data (no API key needed)
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) — Telegram bot framework
- SQLite — price history and config storage
- Docker — containerized deployment
