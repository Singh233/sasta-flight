# SastaFlight - Design Document

## Overview

Single-user Telegram bot that scans Google Flights daily and sends a summary of the cheapest days to fly for configured routes. Self-deployable on Railway.

## Core Decisions

- **Single-user per deployment** — no users table, config via env vars + SQLite key-value
- **`fli` (flights) library** — uses Google Flights internal API (`GetCalendarGraph` endpoint), returns 30 days of prices in 1 API call
- **2 API calls per route** — `SearchDates` for 30-day prices, `SearchFlights` for cheapest day's flight details
- **Direct commands** — `/add ATQ BOM` instead of conversational wizard
- **python-telegram-bot's JobQueue** — built-in scheduling, no separate APScheduler dependency
- **One retry on failure** — retry 4 hours later, then send failure message
- **Airport validation** — let the API validate codes, fail gracefully with error message

## Commands

| Command | Example | What it does |
|---------|---------|-------------|
| `/start` | `/start` | Welcome message + help |
| `/add ATQ BOM` | `/add DEL BLR` | Add a route to watch |
| `/remove 2` | `/remove 1` | Remove route by ID |
| `/routes` | — | List all active routes |
| `/check` | — | Run scan now for all routes |
| `/time 07:30` | `/time 22:00` | Change daily scan time (24h, IST) |
| `/history` | — | 7-day price trend (text bar chart) |
| `/pause` | — | Pause daily updates |
| `/resume` | — | Resume daily updates |
| `/help` | — | Show all commands |

## Database Schema (SQLite)

```sql
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Stores: notify_time (default '08:00'), is_paused (default '0')

CREATE TABLE routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_airport TEXT NOT NULL,
    to_airport TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id INTEGER NOT NULL,
    scan_date TEXT NOT NULL,
    cheapest_travel_date TEXT NOT NULL,
    cheapest_price REAL NOT NULL,
    cheapest_airline TEXT,
    avg_price REAL,
    price_data TEXT,  -- JSON of top 5 days
    scanned_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (route_id) REFERENCES routes(id)
);
```

## Scanning Flow (per route)

1. `SearchDates` — single call, get prices for next 30 days
2. Sort by price, take top 5
3. `SearchFlights` — single call for cheapest day, get airline/time/duration/stops
4. Store cheapest price + top 5 in `price_history`
5. Format message, send to `TELEGRAM_CHAT_ID`

## Daily Schedule

- On startup: read `notify_time` from DB (default `08:00` IST), schedule daily job via `JobQueue`
- Job: check `is_paused` flag, scan all active routes, send formatted messages
- On failure: schedule one-time retry 4 hours later. If retry fails, send failure message.
- `/time` updates DB and reschedules the job
- `/pause` and `/resume` toggle `is_paused` in config

## Daily Message Format

```
✈️ ATQ → BOM | Next 30 Days
━━━━━━━━━━━━━━━━━━━━━━

🏆 Cheapest: Mar 18 (Tue) - ₹3,200
   IndiGo | 6:00 AM | 2h 45m | Nonstop

📊 Top 5 Cheapest Days:
 1. Mar 18 (Tue) - ₹3,200 (IndiGo)
 2. Mar 20 (Thu) - ₹3,450 (SpiceJet)
 3. Mar 25 (Tue) - ₹3,500 (IndiGo)
 4. Mar 12 (Wed) - ₹3,800 (Air India)
 5. Mar 15 (Sat) - ₹4,100 (IndiGo)

📈 Avg: ₹5,200 | Low: ₹3,200 | High: ₹8,900

💡 Trend: Prices dropped 8% since yesterday
```

Trend line only shown when 2+ days of history exist.

## History Command Output

```
📉 ATQ → BOM | 7-Day Price Trend
━━━━━━━━━━━━━━━━━━━━━━━━

Mar 01: ₹3,800  ████████████
Mar 02: ₹4,200  █████████████░
Mar 03: ₹3,500  ███████████
Mar 04: ₹3,200  ██████████
Mar 05: ₹3,600  ███████████░
Mar 06: ₹3,100  █████████░  ← lowest
Mar 07: ₹3,400  ██████████░

📉 Trend: Down 10% this week
💡 Best day to fly found today: Mar 22 @ ₹3,100
```

## Project Structure

```
sasta-flight/
├── bot/
│   ├── __init__.py
│   ├── main.py          # Entry point, bot + job setup
│   ├── handlers.py      # Command handlers
│   ├── scanner.py       # Fli wrapper (SearchDates + SearchFlights)
│   ├── db.py            # SQLite operations
│   ├── formatter.py     # Telegram message formatting
│   └── config.py        # Env vars and constants
├── data/                # SQLite DB (volume mount)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## Environment Variables

```
TELEGRAM_BOT_TOKEN=     # from BotFather
TELEGRAM_CHAT_ID=       # your chat ID
DAYS_TO_SCAN=30         # optional, default 30
TOP_CHEAPEST=5          # optional, default 5
TIMEZONE=Asia/Kolkata   # optional, default IST
```

## Dependencies

```
flights>=0.7.0
python-telegram-bot[job-queue]>=21.0
aiosqlite>=0.20
python-dotenv>=1.0
```

## Deployment

Primary target: Railway (one-click deploy from GitHub).
Also supports: Docker Compose on any VPS, or local Python run.

README will include step-by-step instructions for all three methods.
