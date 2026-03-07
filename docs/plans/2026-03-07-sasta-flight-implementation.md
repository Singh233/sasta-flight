# SastaFlight Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a single-user Telegram bot that scans Google Flights daily via the `fli` library and sends cheapest flight day summaries.

**Architecture:** Python bot using `python-telegram-bot` for Telegram polling + built-in `JobQueue` for daily scheduling. `fli` library for Google Flights data (2 API calls per route). SQLite via `aiosqlite` for persistence. Single-user, configured via env vars.

**Tech Stack:** Python 3.12+, `fli` (flights), `python-telegram-bot[job-queue]`, `aiosqlite`, `python-dotenv`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `bot/__init__.py`
- Create: `bot/config.py`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`

**Step 1: Create requirements.txt**

```
flights>=0.7.0
python-telegram-bot[job-queue]>=21.0
aiosqlite>=0.20
python-dotenv>=1.0
```

**Step 2: Create .env.example**

```
TELEGRAM_BOT_TOKEN=your-bot-token-from-botfather
TELEGRAM_CHAT_ID=your-chat-id
DAYS_TO_SCAN=30
TOP_CHEAPEST=5
TIMEZONE=Asia/Kolkata
```

**Step 3: Create .gitignore**

```
.env
__pycache__/
*.pyc
data/*.db
.venv/
```

**Step 4: Create bot/__init__.py**

Empty file.

**Step 5: Create bot/config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])
DAYS_TO_SCAN = int(os.getenv("DAYS_TO_SCAN", "30"))
TOP_CHEAPEST = int(os.getenv("TOP_CHEAPEST", "5"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
DB_PATH = os.getenv("DB_PATH", "data/flights.db")
```

**Step 6: Install dependencies**

Run: `pip install -r requirements.txt`

**Step 7: Commit**

```bash
git init
git add bot/__init__.py bot/config.py requirements.txt .env.example .gitignore
git commit -m "feat: project scaffolding with config and dependencies"
```

---

### Task 2: Database Layer

**Files:**
- Create: `bot/db.py`
- Create: `tests/test_db.py`

**Step 1: Write failing tests for db operations**

```python
# tests/test_db.py
import pytest
import os
import json
from bot.db import Database

TEST_DB = "data/test_flights.db"


@pytest.fixture
async def db():
    os.makedirs("data", exist_ok=True)
    database = Database(TEST_DB)
    await database.init()
    yield database
    await database.close()
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


@pytest.mark.asyncio
async def test_init_creates_tables(db):
    config = await db.get_config("notify_time")
    assert config == "08:00"
    paused = await db.get_config("is_paused")
    assert paused == "0"


@pytest.mark.asyncio
async def test_set_and_get_config(db):
    await db.set_config("notify_time", "10:30")
    assert await db.get_config("notify_time") == "10:30"


@pytest.mark.asyncio
async def test_add_and_get_routes(db):
    route_id = await db.add_route("ATQ", "BOM")
    routes = await db.get_active_routes()
    assert len(routes) == 1
    assert routes[0]["id"] == route_id
    assert routes[0]["from_airport"] == "ATQ"
    assert routes[0]["to_airport"] == "BOM"


@pytest.mark.asyncio
async def test_remove_route(db):
    route_id = await db.add_route("ATQ", "BOM")
    removed = await db.remove_route(route_id)
    assert removed is True
    routes = await db.get_active_routes()
    assert len(routes) == 0


@pytest.mark.asyncio
async def test_remove_nonexistent_route(db):
    removed = await db.remove_route(999)
    assert removed is False


@pytest.mark.asyncio
async def test_save_and_get_price_history(db):
    route_id = await db.add_route("ATQ", "BOM")
    price_data = json.dumps([{"date": "2026-03-18", "price": 3200}])
    await db.save_price_history(
        route_id=route_id,
        scan_date="2026-03-07",
        cheapest_travel_date="2026-03-18",
        cheapest_price=3200.0,
        cheapest_airline="IndiGo",
        avg_price=5200.0,
        price_data=price_data,
    )
    history = await db.get_price_history(route_id, days=7)
    assert len(history) == 1
    assert history[0]["cheapest_price"] == 3200.0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL (module not found)

**Step 3: Implement bot/db.py**

```python
import aiosqlite
import os


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db: aiosqlite.Connection | None = None

    async def init(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_airport TEXT NOT NULL,
                to_airport TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER NOT NULL,
                scan_date TEXT NOT NULL,
                cheapest_travel_date TEXT NOT NULL,
                cheapest_price REAL NOT NULL,
                cheapest_airline TEXT,
                avg_price REAL,
                price_data TEXT,
                scanned_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (route_id) REFERENCES routes(id)
            );

            INSERT OR IGNORE INTO config (key, value) VALUES ('notify_time', '08:00');
            INSERT OR IGNORE INTO config (key, value) VALUES ('is_paused', '0');
            """
        )
        await self.db.commit()

    async def close(self):
        if self.db:
            await self.db.close()

    async def get_config(self, key: str) -> str | None:
        cursor = await self.db.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row["value"] if row else None

    async def set_config(self, key: str, value: str):
        await self.db.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value),
        )
        await self.db.commit()

    async def add_route(self, from_airport: str, to_airport: str) -> int:
        cursor = await self.db.execute(
            "INSERT INTO routes (from_airport, to_airport) VALUES (?, ?)",
            (from_airport.upper(), to_airport.upper()),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get_active_routes(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT id, from_airport, to_airport FROM routes WHERE is_active = 1"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def remove_route(self, route_id: int) -> bool:
        cursor = await self.db.execute(
            "UPDATE routes SET is_active = 0 WHERE id = ? AND is_active = 1",
            (route_id,),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def save_price_history(
        self,
        route_id: int,
        scan_date: str,
        cheapest_travel_date: str,
        cheapest_price: float,
        cheapest_airline: str | None,
        avg_price: float | None,
        price_data: str | None,
    ):
        await self.db.execute(
            """INSERT INTO price_history
            (route_id, scan_date, cheapest_travel_date, cheapest_price, cheapest_airline, avg_price, price_data)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (route_id, scan_date, cheapest_travel_date, cheapest_price, cheapest_airline, avg_price, price_data),
        )
        await self.db.commit()

    async def get_price_history(self, route_id: int, days: int = 7) -> list[dict]:
        cursor = await self.db.execute(
            """SELECT scan_date, cheapest_travel_date, cheapest_price, cheapest_airline, avg_price, price_data
            FROM price_history
            WHERE route_id = ?
            ORDER BY scan_date DESC
            LIMIT ?""",
            (route_id, days),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add bot/db.py tests/test_db.py
git commit -m "feat: database layer with config, routes, and price history"
```

---

### Task 3: Flight Scanner

**Files:**
- Create: `bot/scanner.py`
- Create: `tests/test_scanner.py`

**Step 1: Write failing tests**

```python
# tests/test_scanner.py
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from bot.scanner import scan_route_dates, scan_flight_details, ScanResult


@pytest.fixture
def mock_date_results():
    """Simulate fli SearchDates response."""
    results = []
    for i, price in enumerate([5000, 3200, 4500, 3800, 6000, 3500, 4200], start=1):
        mock = MagicMock()
        mock.date = [datetime(2026, 4, i)]
        mock.price = price
        results.append(mock)
    return results


@pytest.fixture
def mock_flight_results():
    """Simulate fli SearchFlights response."""
    leg = MagicMock()
    leg.airline.value = "IndiGo"
    leg.departure_datetime = datetime(2026, 4, 2, 6, 0)
    leg.arrival_datetime = datetime(2026, 4, 2, 8, 45)
    leg.departure_airport.value = "ATQ"
    leg.arrival_airport.value = "BOM"

    flight = MagicMock()
    flight.price = 3200
    flight.duration = 165
    flight.stops = 0
    flight.legs = [leg]
    return [flight]


@pytest.mark.asyncio
async def test_scan_route_dates(mock_date_results):
    with patch("bot.scanner.SearchDates") as MockSearch:
        MockSearch.return_value.search.return_value = mock_date_results
        result = await scan_route_dates("ATQ", "BOM", days=7)

    assert len(result) == 7
    assert result[0]["price"] == 3200  # sorted cheapest first
    assert result[0]["date"] == "2026-04-02"


@pytest.mark.asyncio
async def test_scan_flight_details(mock_flight_results):
    with patch("bot.scanner.SearchFlights") as MockSearch:
        MockSearch.return_value.search.return_value = mock_flight_results
        result = await scan_flight_details("ATQ", "BOM", "2026-04-02")

    assert result["price"] == 3200
    assert result["airline"] == "IndiGo"
    assert result["duration"] == 165
    assert result["stops"] == 0


@pytest.mark.asyncio
async def test_scan_route_dates_empty():
    with patch("bot.scanner.SearchDates") as MockSearch:
        MockSearch.return_value.search.return_value = []
        result = await scan_route_dates("ATQ", "BOM", days=7)

    assert result == []


@pytest.mark.asyncio
async def test_scan_route_full(mock_date_results, mock_flight_results):
    with patch("bot.scanner.SearchDates") as MockDates, \
         patch("bot.scanner.SearchFlights") as MockFlights:
        MockDates.return_value.search.return_value = mock_date_results
        MockFlights.return_value.search.return_value = mock_flight_results

        result = await scan_route("ATQ", "BOM")

    assert result is not None
    assert result.cheapest_price == 3200
    assert result.cheapest_airline == "IndiGo"
    assert len(result.top_days) == 5


# Import scan_route here to avoid import issues at top
from bot.scanner import scan_route
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scanner.py -v`
Expected: FAIL (module not found)

**Step 3: Implement bot/scanner.py**

```python
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.search import SearchDates, SearchFlights

from bot.config import DAYS_TO_SCAN, TOP_CHEAPEST

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    from_airport: str
    to_airport: str
    cheapest_price: float
    cheapest_travel_date: str
    cheapest_airline: str | None
    cheapest_departure: str | None
    cheapest_duration: int | None
    cheapest_stops: int | None
    top_days: list[dict]
    avg_price: float
    min_price: float
    max_price: float


def _get_airport(code: str):
    """Try to get Airport enum, fall back to raw string."""
    try:
        return Airport[code.upper()]
    except KeyError:
        return code.upper()


async def scan_route_dates(from_code: str, to_code: str, days: int = DAYS_TO_SCAN) -> list[dict]:
    """Get prices for the next N days. Returns list of {date, price} sorted by price."""
    tomorrow = datetime.now() + timedelta(days=1)
    end_date = tomorrow + timedelta(days=days)

    filters = DateSearchFilters(
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[_get_airport(from_code), 0]],
                arrival_airport=[[_get_airport(to_code), 0]],
                travel_date=tomorrow.strftime("%Y-%m-%d"),
            )
        ],
        from_date=tomorrow.strftime("%Y-%m-%d"),
        to_date=end_date.strftime("%Y-%m-%d"),
    )

    search = SearchDates()
    results = await asyncio.to_thread(search.search, filters)

    date_prices = []
    for r in results:
        date_prices.append({
            "date": r.date[0].strftime("%Y-%m-%d"),
            "price": r.price,
        })

    return sorted(date_prices, key=lambda x: x["price"])


async def scan_flight_details(from_code: str, to_code: str, travel_date: str) -> dict | None:
    """Get flight details for a specific date. Returns cheapest flight info."""
    filters = FlightSearchFilters(
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[_get_airport(from_code), 0]],
                arrival_airport=[[_get_airport(to_code), 0]],
                travel_date=travel_date,
            )
        ],
        seat_type=SeatType.ECONOMY,
        sort_by=SortBy.CHEAPEST,
    )

    search = SearchFlights()
    flights = await asyncio.to_thread(search.search, filters)

    if not flights:
        return None

    flight = flights[0]
    leg = flight.legs[0] if flight.legs else None

    return {
        "price": flight.price,
        "airline": leg.airline.value if leg else None,
        "departure": leg.departure_datetime.strftime("%I:%M %p") if leg else None,
        "duration": flight.duration,
        "stops": flight.stops,
    }


async def scan_route(from_code: str, to_code: str) -> ScanResult | None:
    """Full scan: date prices + flight details for cheapest day."""
    try:
        date_prices = await scan_route_dates(from_code, to_code)
    except Exception:
        logger.exception(f"Failed to scan dates for {from_code} -> {to_code}")
        return None

    if not date_prices:
        logger.warning(f"No prices found for {from_code} -> {to_code}")
        return None

    top_days = date_prices[:TOP_CHEAPEST]
    all_prices = [d["price"] for d in date_prices]
    cheapest = top_days[0]

    # Get flight details for cheapest day
    details = None
    try:
        details = await scan_flight_details(from_code, to_code, cheapest["date"])
    except Exception:
        logger.exception(f"Failed to get flight details for {cheapest['date']}")

    return ScanResult(
        from_airport=from_code.upper(),
        to_airport=to_code.upper(),
        cheapest_price=cheapest["price"],
        cheapest_travel_date=cheapest["date"],
        cheapest_airline=details["airline"] if details else None,
        cheapest_departure=details["departure"] if details else None,
        cheapest_duration=details["duration"] if details else None,
        cheapest_stops=details["stops"] if details else None,
        top_days=top_days,
        avg_price=sum(all_prices) / len(all_prices),
        min_price=min(all_prices),
        max_price=max(all_prices),
    )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scanner.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add bot/scanner.py tests/test_scanner.py
git commit -m "feat: flight scanner with fli library wrapper"
```

---

### Task 4: Message Formatter

**Files:**
- Create: `bot/formatter.py`
- Create: `tests/test_formatter.py`

**Step 1: Write failing tests**

```python
# tests/test_formatter.py
import pytest
from bot.formatter import format_daily_message, format_history_message
from bot.scanner import ScanResult


def test_format_daily_message_basic():
    result = ScanResult(
        from_airport="ATQ",
        to_airport="BOM",
        cheapest_price=3200,
        cheapest_travel_date="2026-03-18",
        cheapest_airline="IndiGo",
        cheapest_departure="06:00 AM",
        cheapest_duration=165,
        cheapest_stops=0,
        top_days=[
            {"date": "2026-03-18", "price": 3200},
            {"date": "2026-03-20", "price": 3450},
            {"date": "2026-03-25", "price": 3500},
        ],
        avg_price=5200,
        min_price=3200,
        max_price=8900,
    )
    msg = format_daily_message(result)
    assert "ATQ" in msg
    assert "BOM" in msg
    assert "3,200" in msg
    assert "IndiGo" in msg
    assert "Nonstop" in msg


def test_format_daily_message_with_trend():
    result = ScanResult(
        from_airport="ATQ",
        to_airport="BOM",
        cheapest_price=3200,
        cheapest_travel_date="2026-03-18",
        cheapest_airline="IndiGo",
        cheapest_departure="06:00 AM",
        cheapest_duration=165,
        cheapest_stops=0,
        top_days=[{"date": "2026-03-18", "price": 3200}],
        avg_price=5200,
        min_price=3200,
        max_price=8900,
    )
    msg = format_daily_message(result, prev_cheapest=3500)
    assert "dropped" in msg.lower() or "↓" in msg.lower() or "down" in msg.lower()


def test_format_daily_message_no_details():
    """When flight details are unavailable."""
    result = ScanResult(
        from_airport="ATQ",
        to_airport="BOM",
        cheapest_price=3200,
        cheapest_travel_date="2026-03-18",
        cheapest_airline=None,
        cheapest_departure=None,
        cheapest_duration=None,
        cheapest_stops=None,
        top_days=[{"date": "2026-03-18", "price": 3200}],
        avg_price=5200,
        min_price=3200,
        max_price=8900,
    )
    msg = format_daily_message(result)
    assert "3,200" in msg


def test_format_history_message():
    history = [
        {"scan_date": "2026-03-07", "cheapest_price": 3400},
        {"scan_date": "2026-03-06", "cheapest_price": 3100},
        {"scan_date": "2026-03-05", "cheapest_price": 3600},
        {"scan_date": "2026-03-04", "cheapest_price": 3200},
        {"scan_date": "2026-03-03", "cheapest_price": 3500},
    ]
    msg = format_history_message("ATQ", "BOM", history)
    assert "ATQ" in msg
    assert "BOM" in msg
    assert "3,100" in msg  # lowest should appear
    assert "█" in msg  # bar chart
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_formatter.py -v`
Expected: FAIL

**Step 3: Implement bot/formatter.py**

```python
from datetime import datetime
from bot.scanner import ScanResult


def _format_price(price: float) -> str:
    return f"₹{price:,.0f}"


def _format_date(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%b %d (%a)")


def _format_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m"


def _format_stops(stops: int) -> str:
    if stops == 0:
        return "Nonstop"
    return f"{stops} stop{'s' if stops > 1 else ''}"


def format_daily_message(result: ScanResult, prev_cheapest: float | None = None) -> str:
    lines = [
        f"✈️ {result.from_airport} → {result.to_airport} | Next 30 Days",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    # Cheapest day header
    cheapest_line = f"🏆 Cheapest: {_format_date(result.cheapest_travel_date)} - {_format_price(result.cheapest_price)}"
    lines.append(cheapest_line)

    if result.cheapest_airline:
        detail_parts = [result.cheapest_airline]
        if result.cheapest_departure:
            detail_parts.append(result.cheapest_departure)
        if result.cheapest_duration is not None:
            detail_parts.append(_format_duration(result.cheapest_duration))
        if result.cheapest_stops is not None:
            detail_parts.append(_format_stops(result.cheapest_stops))
        lines.append(f"   {' | '.join(detail_parts)}")

    lines.append("")

    # Top cheapest days
    lines.append(f"📊 Top {len(result.top_days)} Cheapest Days:")
    for i, day in enumerate(result.top_days, 1):
        lines.append(f" {i}. {_format_date(day['date'])} - {_format_price(day['price'])}")

    lines.append("")

    # Stats
    lines.append(
        f"📈 Avg: {_format_price(result.avg_price)} | "
        f"Low: {_format_price(result.min_price)} | "
        f"High: {_format_price(result.max_price)}"
    )

    # Trend
    if prev_cheapest is not None:
        pct = ((result.cheapest_price - prev_cheapest) / prev_cheapest) * 100
        if pct < 0:
            lines.append(f"\n💡 Trend: Prices dropped {abs(pct):.0f}% since yesterday")
        elif pct > 0:
            lines.append(f"\n💡 Trend: Prices rose {pct:.0f}% since yesterday")
        else:
            lines.append("\n💡 Trend: Prices unchanged since yesterday")

    return "\n".join(lines)


def format_history_message(from_airport: str, to_airport: str, history: list[dict]) -> str:
    if not history:
        return f"📉 {from_airport} → {to_airport} | No history yet"

    # History comes DESC from DB, reverse for display
    history = list(reversed(history))

    prices = [h["cheapest_price"] for h in history]
    min_price = min(prices)
    max_price = max(prices)
    price_range = max_price - min_price if max_price != min_price else 1

    lines = [
        f"📉 {from_airport} → {to_airport} | {len(history)}-Day Price Trend",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    max_bar_len = 15
    for h in history:
        price = h["cheapest_price"]
        bar_len = int(((price - min_price) / price_range) * max_bar_len) + 1
        bar = "█" * bar_len
        date_str = datetime.strptime(h["scan_date"], "%Y-%m-%d").strftime("%b %d")
        marker = "  ← lowest" if price == min_price else ""
        lines.append(f"{date_str}: {_format_price(price)}  {bar}{marker}")

    lines.append("")

    # Trend
    if len(prices) >= 2:
        pct = ((prices[-1] - prices[0]) / prices[0]) * 100
        direction = "Down" if pct < 0 else "Up"
        lines.append(f"📉 Trend: {direction} {abs(pct):.0f}% this week")

    # Best day found in latest scan
    latest = history[-1]
    lines.append(
        f"💡 Best day to fly found today: {_format_date(latest.get('cheapest_travel_date', latest['scan_date']))} @ {_format_price(latest['cheapest_price'])}"
    )

    return "\n".join(lines)


def format_error_message(from_airport: str, to_airport: str) -> str:
    return (
        f"⚠️ {from_airport} → {to_airport}\n"
        "Scan failed. Will retry in 4 hours.\n"
        "If this keeps happening, the flight data library may need updating."
    )


def format_retry_failed_message(from_airport: str, to_airport: str) -> str:
    return (
        f"❌ {from_airport} → {to_airport}\n"
        "Scan failed after retry. Will try again tomorrow.\n"
        "Run /check to try manually."
    )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_formatter.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add bot/formatter.py tests/test_formatter.py
git commit -m "feat: message formatter for daily reports and history"
```

---

### Task 5: Telegram Command Handlers

**Files:**
- Create: `bot/handlers.py`

**Step 1: Implement all command handlers**

```python
# bot/handlers.py
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import CHAT_ID
from bot.db import Database
from bot.scanner import scan_route
from bot.formatter import (
    format_daily_message,
    format_error_message,
    format_history_message,
)

logger = logging.getLogger(__name__)

# Global db reference, set in main.py
db: Database = None


def _is_authorized(update: Update) -> bool:
    return update.effective_chat.id == CHAT_ID


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await update.message.reply_text(
        "✈️ SastaFlight - Daily Flight Price Scanner\n\n"
        "Commands:\n"
        "/add <from> <to> - Add a route (e.g. /add ATQ BOM)\n"
        "/remove <id> - Remove a route\n"
        "/routes - List active routes\n"
        "/check - Scan all routes now\n"
        "/time <HH:MM> - Set daily scan time (24h, IST)\n"
        "/history - 7-day price trend\n"
        "/pause - Pause daily updates\n"
        "/resume - Resume daily updates\n"
        "/help - Show this message"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await start_command(update, context)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Usage: /add <from> <to>\nExample: /add ATQ BOM")
        return

    from_code = context.args[0].upper()
    to_code = context.args[1].upper()

    if len(from_code) != 3 or len(to_code) != 3:
        await update.message.reply_text("Airport codes must be 3 letters (IATA codes).")
        return

    route_id = await db.add_route(from_code, to_code)
    await update.message.reply_text(
        f"✅ Route added: {from_code} → {to_code} (ID: {route_id})\n"
        "Use /check to run a scan now."
    )


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /remove <id>\nUse /routes to see route IDs.")
        return

    try:
        route_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Route ID must be a number.")
        return

    removed = await db.remove_route(route_id)
    if removed:
        await update.message.reply_text(f"✅ Route {route_id} removed.")
    else:
        await update.message.reply_text(f"❌ Route {route_id} not found.")


async def routes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    routes = await db.get_active_routes()
    if not routes:
        await update.message.reply_text("No active routes. Use /add to add one.")
        return

    lines = ["📋 Active Routes:\n"]
    for r in routes:
        lines.append(f"  {r['id']}. {r['from_airport']} → {r['to_airport']}")
    await update.message.reply_text("\n".join(lines))


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    routes = await db.get_active_routes()
    if not routes:
        await update.message.reply_text("No active routes. Use /add to add one.")
        return

    await update.message.reply_text("🔍 Scanning... this may take a moment.")

    for route in routes:
        await _scan_and_send(context, route)


async def time_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    if not context.args or len(context.args) != 1:
        current = await db.get_config("notify_time")
        await update.message.reply_text(
            f"Current scan time: {current} IST\nUsage: /time <HH:MM>"
        )
        return

    time_str = context.args[0]
    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        await update.message.reply_text("Invalid format. Use HH:MM (e.g. 08:00, 14:30)")
        return

    await db.set_config("notify_time", time_str)

    # Reschedule - import here to avoid circular
    from bot.main import schedule_daily_job
    await schedule_daily_job(context.application)

    await update.message.reply_text(f"✅ Daily scan time set to {time_str} IST")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    routes = await db.get_active_routes()
    if not routes:
        await update.message.reply_text("No active routes.")
        return

    for route in routes:
        history = await db.get_price_history(route["id"], days=7)
        msg = format_history_message(route["from_airport"], route["to_airport"], history)
        await update.message.reply_text(msg)


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await db.set_config("is_paused", "1")
    await update.message.reply_text("⏸ Daily updates paused. Use /resume to restart.")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await db.set_config("is_paused", "0")
    await update.message.reply_text("▶️ Daily updates resumed.")


async def _scan_and_send(context: ContextTypes.DEFAULT_TYPE, route: dict, is_retry: bool = False):
    """Scan a single route and send the result. Schedule retry on failure."""
    from_code = route["from_airport"]
    to_code = route["to_airport"]

    result = await scan_route(from_code, to_code)

    if result is None:
        if is_retry:
            msg = (
                f"❌ {from_code} → {to_code}\n"
                "Scan failed after retry. Will try again tomorrow.\n"
                "Run /check to try manually."
            )
            await context.bot.send_message(chat_id=CHAT_ID, text=msg)
        else:
            msg = format_error_message(from_code, to_code)
            await context.bot.send_message(chat_id=CHAT_ID, text=msg)
            # Schedule retry in 4 hours
            context.job_queue.run_once(
                _retry_scan_job,
                when=4 * 60 * 60,
                data=route,
                name=f"retry_{route['id']}",
            )
        return

    # Get previous cheapest for trend
    history = await db.get_price_history(route["id"], days=1)
    prev_cheapest = history[0]["cheapest_price"] if history else None

    # Save to history
    import json
    today = datetime.now().strftime("%Y-%m-%d")
    await db.save_price_history(
        route_id=route["id"],
        scan_date=today,
        cheapest_travel_date=result.cheapest_travel_date,
        cheapest_price=result.cheapest_price,
        cheapest_airline=result.cheapest_airline,
        avg_price=result.avg_price,
        price_data=json.dumps(result.top_days),
    )

    msg = format_daily_message(result, prev_cheapest=prev_cheapest)
    await context.bot.send_message(chat_id=CHAT_ID, text=msg)


async def _retry_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Retry a failed scan (called by JobQueue)."""
    route = context.job.data
    await _scan_and_send(context, route, is_retry=True)


async def daily_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Daily scheduled job: scan all routes if not paused."""
    is_paused = await db.get_config("is_paused")
    if is_paused == "1":
        return

    routes = await db.get_active_routes()
    if not routes:
        return

    for route in routes:
        await _scan_and_send(context, route)
```

**Step 2: Commit**

```bash
git add bot/handlers.py
git commit -m "feat: telegram command handlers with scan, retry, and scheduling"
```

---

### Task 6: Main Entry Point

**Files:**
- Create: `bot/main.py`

**Step 1: Implement bot/main.py**

```python
# bot/main.py
import logging
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from telegram.ext import Application, CommandHandler

from bot.config import BOT_TOKEN, TIMEZONE
from bot.db import Database
from bot import handlers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DAILY_JOB_NAME = "daily_scan"


async def schedule_daily_job(application: Application):
    """Schedule or reschedule the daily scan job."""
    # Remove existing daily job
    existing = application.job_queue.get_jobs_by_name(DAILY_JOB_NAME)
    for job in existing:
        job.schedule_removal()

    notify_time = await handlers.db.get_config("notify_time")
    hour, minute = map(int, notify_time.split(":"))
    tz = ZoneInfo(TIMEZONE)

    application.job_queue.run_daily(
        handlers.daily_scan_job,
        time=dt_time(hour=hour, minute=minute, tzinfo=tz),
        name=DAILY_JOB_NAME,
    )
    logger.info(f"Daily scan scheduled at {notify_time} {TIMEZONE}")


async def post_init(application: Application):
    """Called after bot is initialized."""
    db = Database()
    await db.init()
    handlers.db = db
    await schedule_daily_job(application)
    logger.info("SastaFlight bot started")


async def post_shutdown(application: Application):
    """Called on shutdown."""
    if handlers.db:
        await handlers.db.close()


def main():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("add", handlers.add_command))
    application.add_handler(CommandHandler("remove", handlers.remove_command))
    application.add_handler(CommandHandler("routes", handlers.routes_command))
    application.add_handler(CommandHandler("check", handlers.check_command))
    application.add_handler(CommandHandler("time", handlers.time_command))
    application.add_handler(CommandHandler("history", handlers.history_command))
    application.add_handler(CommandHandler("pause", handlers.pause_command))
    application.add_handler(CommandHandler("resume", handlers.resume_command))

    application.run_polling()


if __name__ == "__main__":
    main()
```

**Step 2: Update bot/db.py constructor to use default from config**

Add a default parameter to `Database.__init__`:

```python
# In bot/db.py, update __init__:
from bot.config import DB_PATH

class Database:
    def __init__(self, db_path: str = DB_PATH):
        ...
```

Note: The test fixture already passes an explicit path, so tests are unaffected.

**Step 3: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add bot/main.py bot/db.py
git commit -m "feat: main entry point with bot setup and daily scheduling"
```

---

### Task 7: Docker & Deployment Setup

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

**Step 1: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "bot.main"]
```

**Step 2: Create docker-compose.yml**

```yaml
services:
  bot:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data
```

**Step 3: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: docker setup for deployment"
```

---

### Task 8: README with Deployment Guide

**Files:**
- Create: `README.md`

**Step 1: Write README**

````markdown
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
````

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with deployment guide for Railway, Docker, and local"
```

---

### Task 9: End-to-End Manual Test

**Step 1: Set up .env with real credentials**

```bash
cp .env.example .env
# Edit .env with your actual TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
```

**Step 2: Run the bot locally**

Run: `python -m bot.main`

**Step 3: Test commands in Telegram**

1. Send `/start` — should see welcome message
2. Send `/add ATQ BOM` — should confirm route added
3. Send `/check` — should scan and send price report
4. Send `/routes` — should list the route
5. Send `/history` — should show "no history" or first data point
6. Send `/time 10:00` — should confirm time change
7. Send `/pause` then `/resume` — should toggle
8. Send `/remove 1` — should confirm removal

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: ready for deployment"
```
