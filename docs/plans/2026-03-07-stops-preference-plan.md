# Stops Preference Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add stops preference filtering (global default + per-route override) with inline keyboard UX.

**Architecture:** Store stops preference in SQLite (`config` table for global, `routes.max_stops` for per-route). Pass `fli.MaxStops` enum to `FlightSearchFilters.stops` at scan time. For accuracy, validate each top-N date by fetching flight details with stops filter, skipping dates with no matching flights.

**Tech Stack:** Python 3.12+, fli (flights library), python-telegram-bot (InlineKeyboardButton/CallbackQueryHandler), aiosqlite

---

### Task 1: Database — Schema Migration and New Methods

**Files:**
- Modify: `bot/db.py:12-48` (init method), `bot/db.py:68-81` (add_route, get_active_routes)
- Test: `tests/test_db.py`

**Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_init_creates_stops_preference(db):
    config = await db.get_config("stops_preference")
    assert config == "any"


@pytest.mark.asyncio
async def test_add_route_default_max_stops(db):
    route_id = await db.add_route("ATQ", "BOM")
    routes = await db.get_active_routes()
    assert routes[0]["max_stops"] is None


@pytest.mark.asyncio
async def test_add_route_with_max_stops(db):
    route_id = await db.add_route("ATQ", "BOM", max_stops="direct")
    routes = await db.get_active_routes()
    assert routes[0]["max_stops"] == "direct"


@pytest.mark.asyncio
async def test_set_route_stops(db):
    route_id = await db.add_route("ATQ", "BOM")
    updated = await db.set_route_stops(route_id, "1stop")
    assert updated is True
    routes = await db.get_active_routes()
    assert routes[0]["max_stops"] == "1stop"


@pytest.mark.asyncio
async def test_set_route_stops_nonexistent(db):
    updated = await db.set_route_stops(999, "direct")
    assert updated is False


@pytest.mark.asyncio
async def test_get_route_stops_preference_per_route(db):
    route_id = await db.add_route("ATQ", "BOM", max_stops="direct")
    pref = await db.get_route_stops_preference(route_id)
    assert pref == "direct"


@pytest.mark.asyncio
async def test_get_route_stops_preference_falls_back_to_global(db):
    route_id = await db.add_route("ATQ", "BOM")
    pref = await db.get_route_stops_preference(route_id)
    assert pref == "any"


@pytest.mark.asyncio
async def test_get_route_stops_preference_custom_global(db):
    route_id = await db.add_route("ATQ", "BOM")
    await db.set_config("stops_preference", "1stop")
    pref = await db.get_route_stops_preference(route_id)
    assert pref == "1stop"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py -v`
Expected: Multiple FAILs — missing column `max_stops`, missing methods

**Step 3: Implement database changes**

In `bot/db.py`:

1. Add `max_stops TEXT DEFAULT NULL` column to routes CREATE TABLE (line 25):
```python
            CREATE TABLE IF NOT EXISTS routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_airport TEXT NOT NULL,
                to_airport TEXT NOT NULL,
                max_stops TEXT DEFAULT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );
```

2. Add migration after the CREATE TABLE block (after line 46, before `await self.db.commit()`):
```python
            INSERT OR IGNORE INTO config (key, value) VALUES ('stops_preference', 'any');
```

3. Add migration for existing DBs (after executescript, before commit):
```python
        # Migrate: add max_stops column if missing
        try:
            await self.db.execute("ALTER TABLE routes ADD COLUMN max_stops TEXT DEFAULT NULL")
            await self.db.commit()
        except Exception:
            pass  # Column already exists
```

4. Update `add_route` method (line 68) to accept `max_stops`:
```python
    async def add_route(self, from_airport: str, to_airport: str, max_stops: str | None = None) -> int:
        cursor = await self.db.execute(
            "INSERT INTO routes (from_airport, to_airport, max_stops) VALUES (?, ?, ?)",
            (from_airport.upper(), to_airport.upper(), max_stops),
        )
        await self.db.commit()
        return cursor.lastrowid
```

5. Update `get_active_routes` (line 76) to include `max_stops`:
```python
    async def get_active_routes(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT id, from_airport, to_airport, max_stops FROM routes WHERE is_active = 1"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

6. Add new methods after `remove_route`:
```python
    async def set_route_stops(self, route_id: int, max_stops: str) -> bool:
        cursor = await self.db.execute(
            "UPDATE routes SET max_stops = ? WHERE id = ? AND is_active = 1",
            (max_stops, route_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def get_route_stops_preference(self, route_id: int) -> str:
        cursor = await self.db.execute(
            "SELECT max_stops FROM routes WHERE id = ?", (route_id,)
        )
        row = await cursor.fetchone()
        if row and row["max_stops"]:
            return row["max_stops"]
        return await self.get_config("stops_preference") or "any"
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add bot/db.py tests/test_db.py
git commit -m "feat: database support for stops preference (global + per-route)"
```

---

### Task 2: Scanner — Pass max_stops to fli API with Per-Date Validation

**Files:**
- Modify: `bot/scanner.py:6-14` (imports), `bot/scanner.py:77-107` (scan_flight_details), `bot/scanner.py:110-146` (scan_route)
- Test: `tests/test_scanner.py`

**Step 1: Write the failing tests**

Add to `tests/test_scanner.py` (before the `from bot.scanner import scan_route` line at bottom):

```python
from fli.models import MaxStops


@pytest.mark.asyncio
async def test_scan_flight_details_with_max_stops(mock_flight_results):
    with patch("bot.scanner.SearchFlights") as MockSearch:
        MockSearch.return_value.search.return_value = mock_flight_results
        result = await scan_flight_details("ATQ", "BOM", "2026-04-02", max_stops="direct")

    # Verify MaxStops was passed to filters
    call_args = MockSearch.return_value.search.call_args[0][0]
    assert call_args.stops == MaxStops.NON_STOP


@pytest.mark.asyncio
async def test_scan_flight_details_default_max_stops(mock_flight_results):
    with patch("bot.scanner.SearchFlights") as MockSearch:
        MockSearch.return_value.search.return_value = mock_flight_results
        result = await scan_flight_details("ATQ", "BOM", "2026-04-02")

    call_args = MockSearch.return_value.search.call_args[0][0]
    assert call_args.stops == MaxStops.ANY


@pytest.mark.asyncio
async def test_scan_route_skips_dates_without_matching_flights(mock_date_results):
    """When stops filter causes some dates to have no flights, skip them."""
    with patch("bot.scanner.SearchDates") as MockDates, \
         patch("bot.scanner.SearchFlights") as MockFlights:
        MockDates.return_value.search.return_value = mock_date_results
        # First 2 dates return no flights, 3rd returns a flight
        empty_results = []
        leg = MagicMock()
        leg.airline.value = "IndiGo"
        leg.departure_datetime = datetime(2026, 4, 5, 6, 0)
        valid_flight = MagicMock()
        valid_flight.price = 4500
        valid_flight.duration = 165
        valid_flight.stops = 0
        valid_flight.legs = [leg]
        MockFlights.return_value.search.side_effect = [
            [],  # date 1: no matching flights
            [],  # date 2: no matching flights
            [valid_flight],  # date 3: match
            [valid_flight],  # date 4: match
            [valid_flight],  # date 5: match
            [valid_flight],  # date 6: match
            [valid_flight],  # date 7: match
        ]

        result = await scan_route("ATQ", "BOM", max_stops="direct")

    assert result is not None
    assert len(result.top_days) == 5  # still gets 5 valid days
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scanner.py -v`
Expected: FAIL — `scan_flight_details()` and `scan_route()` don't accept `max_stops`

**Step 3: Implement scanner changes**

In `bot/scanner.py`:

1. Add `MaxStops` to imports (line 6-14):
```python
from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)
```

2. Add mapping constant after imports (after line 17):
```python
STOPS_MAP = {
    "any": MaxStops.ANY,
    "direct": MaxStops.NON_STOP,
    "1stop": MaxStops.ONE_STOP_OR_FEWER,
    "2stops": MaxStops.TWO_OR_FEWER_STOPS,
}
```

3. Update `scan_flight_details` signature and body (line 77):
```python
async def scan_flight_details(from_code: str, to_code: str, travel_date: str, max_stops: str = "any") -> dict | None:
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
        stops=STOPS_MAP.get(max_stops, MaxStops.ANY),
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
```

4. Update `scan_route` to accept `max_stops` and validate per-date (line 110):
```python
async def scan_route(from_code: str, to_code: str, max_stops: str = "any") -> ScanResult | None:
    """Full scan: date prices + flight details for cheapest day."""
    try:
        date_prices = await scan_route_dates(from_code, to_code)
    except Exception:
        logger.exception(f"Failed to scan dates for {from_code} -> {to_code}")
        return None

    if not date_prices:
        logger.warning(f"No prices found for {from_code} -> {to_code}")
        return None

    all_prices = [d["price"] for d in date_prices]

    # For each date (cheapest first), fetch details with stops filter.
    # Skip dates with no matching flights. Stop at TOP_CHEAPEST valid results.
    top_days = []
    first_details = None

    for day in date_prices:
        try:
            details = await scan_flight_details(from_code, to_code, day["date"], max_stops=max_stops)
        except Exception:
            logger.exception(f"Failed to get flight details for {day['date']}")
            continue

        if details is None:
            continue

        top_days.append({"date": day["date"], "price": details["price"]})
        if first_details is None:
            first_details = details

        if len(top_days) >= TOP_CHEAPEST:
            break

    if not top_days:
        logger.warning(f"No flights matching stops preference for {from_code} -> {to_code}")
        return None

    return ScanResult(
        from_airport=from_code.upper(),
        to_airport=to_code.upper(),
        cheapest_price=top_days[0]["price"],
        cheapest_travel_date=top_days[0]["date"],
        cheapest_airline=first_details["airline"] if first_details else None,
        cheapest_departure=first_details["departure"] if first_details else None,
        cheapest_duration=first_details["duration"] if first_details else None,
        cheapest_stops=first_details["stops"] if first_details else None,
        top_days=top_days,
        avg_price=sum(all_prices) / len(all_prices),
        min_price=min(all_prices),
        max_price=max(all_prices),
    )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scanner.py -v`
Expected: All PASS

**Step 5: Fix existing test**

The existing `test_scan_route_full` test needs updating since `scan_route` now calls `scan_flight_details` for each top day (not just the cheapest). Update the mock setup:

```python
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
```

Note: This test should still pass because `SearchFlights` mock returns `mock_flight_results` for every call. Verify it passes.

**Step 6: Commit**

```bash
git add bot/scanner.py tests/test_scanner.py
git commit -m "feat: scanner passes stops filter to fli API with per-date validation"
```

---

### Task 3: Formatter — Show Filter Label in Header

**Files:**
- Modify: `bot/formatter.py:25-28` (format_daily_message header)
- Test: `tests/test_formatter.py`

**Step 1: Write the failing tests**

Add to `tests/test_formatter.py`:

```python
def test_format_daily_message_with_stops_filter():
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
    msg = format_daily_message(result, stops_label="Direct")
    assert "Filter: Direct" in msg


def test_format_daily_message_no_filter_label_for_any():
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
    assert "Filter" not in msg
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_formatter.py -v`
Expected: FAIL — `format_daily_message()` doesn't accept `stops_label`

**Step 3: Implement formatter changes**

In `bot/formatter.py`, update `format_daily_message` (line 25):

```python
def format_daily_message(result: ScanResult, prev_cheapest: float | None = None, stops_label: str | None = None) -> str:
    header = f"✈️ {result.from_airport} → {result.to_airport} | Next 30 Days"
    if stops_label:
        header += f" | Filter: {stops_label}"
    lines = [
        header,
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
```

The rest of the function stays the same.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_formatter.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add bot/formatter.py tests/test_formatter.py
git commit -m "feat: show stops filter label in scan result header"
```

---

### Task 4: Handlers — `/stops` Command with Inline Keyboard

**Files:**
- Modify: `bot/handlers.py` (add stops_command, callback handler, helper constants)
- Modify: `bot/main.py:61-74` (register new handlers)
- Test: Manual testing via Telegram (inline keyboards are hard to unit test meaningfully)

**Step 1: Add stops constants and keyboard helper to handlers.py**

Add after the imports (after line 17) in `bot/handlers.py`:

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

STOPS_LABELS = {
    "any": "Any",
    "direct": "Direct",
    "1stop": "Up to 1 Stop",
    "2stops": "Up to 2 Stops",
}

STOPS_OPTIONS = list(STOPS_LABELS.keys())


def _stops_keyboard(callback_prefix: str, current: str | None = None) -> InlineKeyboardMarkup:
    """Build inline keyboard for stops selection."""
    buttons = []
    for value, label in STOPS_LABELS.items():
        display = f">> {label} <<" if value == current else label
        buttons.append(InlineKeyboardButton(display, callback_data=f"{callback_prefix}:{value}"))
    return InlineKeyboardMarkup([buttons])
```

**Step 2: Add `/stops` command handler**

Add to `bot/handlers.py` (after `resume_command`):

```python
async def stops_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    current = await db.get_config("stops_preference") or "any"
    keyboard = _stops_keyboard("stops_global", current)
    await update.message.reply_text(
        f"Current default stops preference: {STOPS_LABELS.get(current, current)}\n"
        "Select new default:",
        reply_markup=keyboard,
    )
```

**Step 3: Add callback query handler for all stops callbacks**

Add to `bot/handlers.py`:

```python
async def stops_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks for stops preference."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("stops_global:"):
        value = data.split(":")[1]
        await db.set_config("stops_preference", value)
        await query.edit_message_text(f"✅ Default stops preference set to: {STOPS_LABELS[value]}")

    elif data.startswith("stops_route:"):
        parts = data.split(":")
        route_id = int(parts[1])
        value = parts[2]
        await db.set_route_stops(route_id, value)
        routes = await db.get_active_routes()
        route = next((r for r in routes if r["id"] == route_id), None)
        if route:
            await query.edit_message_text(
                f"✅ {route['from_airport']} → {route['to_airport']} stops set to: {STOPS_LABELS[value]}"
            )
        else:
            await query.edit_message_text(f"✅ Route stops preference updated to: {STOPS_LABELS[value]}")

    elif data.startswith("stops_newroute:"):
        parts = data.split(":")
        route_id = int(parts[1])
        value = parts[2]
        await db.set_route_stops(route_id, value)
        await query.edit_message_text(f"✅ Stops preference set to: {STOPS_LABELS[value]}")
```

**Step 4: Commit**

```bash
git add bot/handlers.py
git commit -m "feat: /stops command and callback handler with inline keyboards"
```

---

### Task 5: Handlers — Update `/add` to Show Stops Keyboard

**Files:**
- Modify: `bot/handlers.py:51-69` (add_command)

**Step 1: Update add_command to show stops keyboard after adding route**

Replace the success reply in `add_command` (lines 65-69):

```python
    route_id = await db.add_route(from_code, to_code)
    keyboard = _stops_keyboard(f"stops_newroute:{route_id}")
    await update.message.reply_text(
        f"✅ Route added: {from_code} → {to_code} (ID: {route_id})\n"
        "Select stops preference for this route:",
        reply_markup=keyboard,
    )
```

**Step 2: Commit**

```bash
git add bot/handlers.py
git commit -m "feat: /add shows inline keyboard for stops preference"
```

---

### Task 6: Handlers — Update `/routes` to Show Stops Info and Change Button

**Files:**
- Modify: `bot/handlers.py:92-103` (routes_command)

**Step 1: Update routes_command**

Replace the `routes_command` function:

```python
async def routes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    routes = await db.get_active_routes()
    if not routes:
        await update.message.reply_text("No active routes. Use /add to add one.")
        return

    global_pref = await db.get_config("stops_preference") or "any"
    lines = ["📋 Active Routes:\n"]
    keyboard_rows = []
    for r in routes:
        effective = r["max_stops"] or global_pref
        label = STOPS_LABELS.get(effective, effective)
        lines.append(f"  {r['id']}. {r['from_airport']} → {r['to_airport']} ({label})")
        keyboard_rows.append([
            InlineKeyboardButton(
                f"Change Stops: {r['from_airport']} → {r['to_airport']}",
                callback_data=f"stops_pick:{r['id']}",
            )
        ])

    markup = InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None
    await update.message.reply_text("\n".join(lines), reply_markup=markup)
```

**Step 2: Add `stops_pick` callback to `stops_callback`**

Add this branch to the `stops_callback` function (inside the if/elif chain):

```python
    elif data.startswith("stops_pick:"):
        route_id = int(data.split(":")[1])
        routes = await db.get_active_routes()
        route = next((r for r in routes if r["id"] == route_id), None)
        if route:
            current = route["max_stops"]
            keyboard = _stops_keyboard(f"stops_route:{route_id}", current)
            await query.edit_message_text(
                f"Select stops preference for {route['from_airport']} → {route['to_airport']}:",
                reply_markup=keyboard,
            )
```

**Step 3: Commit**

```bash
git add bot/handlers.py
git commit -m "feat: /routes shows stops preference and change button per route"
```

---

### Task 7: Handlers — Wire Stops Preference into Scan Flow

**Files:**
- Modify: `bot/handlers.py:174-218` (_scan_and_send), `bot/handlers.py:106-117` (check_command), `bot/handlers.py:227-238` (daily_scan_job)

**Step 1: Update `_scan_and_send` to resolve and pass stops preference**

```python
async def _scan_and_send(context: ContextTypes.DEFAULT_TYPE, route: dict, is_retry: bool = False):
    """Scan a single route and send the result. Schedule retry on failure."""
    from_code = route["from_airport"]
    to_code = route["to_airport"]

    # Resolve stops preference
    max_stops = await db.get_route_stops_preference(route["id"])

    result = await scan_route(from_code, to_code, max_stops=max_stops)

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

    stops_label = STOPS_LABELS.get(max_stops) if max_stops != "any" else None
    msg = format_daily_message(result, prev_cheapest=prev_cheapest, stops_label=stops_label)
    await context.bot.send_message(chat_id=CHAT_ID, text=msg)
```

**Step 2: Commit**

```bash
git add bot/handlers.py
git commit -m "feat: scan flow resolves and applies stops preference per route"
```

---

### Task 8: Main — Register New Handlers and Update Help

**Files:**
- Modify: `bot/main.py:61-74` (handler registration)
- Modify: `bot/handlers.py:27-42` (start_command help text)

**Step 1: Register stops command and callback handler in main.py**

Add import at top of `bot/main.py` (after line 5):
```python
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
```

Add after the existing command handlers (after line 72):
```python
    application.add_handler(CommandHandler("stops", handlers.stops_command))
    application.add_handler(CallbackQueryHandler(handlers.stops_callback))
```

**Step 2: Update help text in start_command**

Update the help text in `bot/handlers.py` `start_command` (lines 30-41):
```python
    await update.message.reply_text(
        "✈️ SastaFlight - Daily Flight Price Scanner\n\n"
        "Commands:\n"
        "/add <from> <to> - Add a route (e.g. /add ATQ BOM)\n"
        "/remove <id> - Remove a route\n"
        "/routes - List active routes\n"
        "/stops - Set default stops preference\n"
        "/check - Scan all routes now\n"
        "/time <HH:MM> - Set daily scan time (24h, IST)\n"
        "/history - 7-day price trend\n"
        "/pause - Pause daily updates\n"
        "/resume - Resume daily updates\n"
        "/help - Show this message"
    )
```

**Step 3: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add bot/main.py bot/handlers.py
git commit -m "feat: register /stops command and callback handler, update help text"
```

---

### Task 9: Final Verification

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

**Step 2: Verify no import errors**

Run: `python -c "from bot.handlers import stops_command, stops_callback; from bot.scanner import STOPS_MAP; print('All imports OK')"`
Expected: `All imports OK`

**Step 3: Review changes**

Run: `git log --oneline` to verify clean commit history
Run: `git diff main` (if on a feature branch) to review all changes
