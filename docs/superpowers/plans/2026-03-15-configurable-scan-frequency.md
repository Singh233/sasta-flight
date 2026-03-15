# Configurable Scan Frequency Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to configure scan frequency (1h–24h) globally and per-route, replacing the single daily scan with per-route repeating jobs.

**Architecture:** Replace `run_daily()` with per-route `run_repeating()` jobs from python-telegram-bot's JobQueue. Store `scan_interval` in the config table (global default) and routes table (per-route override). Resolution follows the same pattern as `stops_preference`.

**Tech Stack:** Python 3.12, python-telegram-bot (JobQueue), aiosqlite, pytest

**Spec:** `docs/superpowers/specs/2026-03-15-configurable-scan-frequency-design.md`

---

## Chunk 1: Data Layer

### Task 1: Add INTERVAL_OPTIONS constant

**Files:**
- Modify: `bot/config.py:1-12`

- [ ] **Step 1: Add INTERVAL_OPTIONS constant to config.py**

Add after the existing constants:

```python
INTERVAL_OPTIONS = {"1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "24h": 1440}
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from bot.config import INTERVAL_OPTIONS; print(INTERVAL_OPTIONS)"`
Expected: prints the dictionary

- [ ] **Step 3: Commit**

```bash
git add bot/config.py
git commit -m "feat: add INTERVAL_OPTIONS constant for scan frequency"
```

---

### Task 2: DB schema migration and scan_interval default config

**Files:**
- Modify: `bot/db.py:12-57` (init and migration)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing test for scan_interval default config**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_init_creates_scan_interval_config(db):
    config = await db.get_config("scan_interval")
    assert config == "1440"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_init_creates_scan_interval_config -v`
Expected: FAIL — `None != "1440"`

- [ ] **Step 3: Add scan_interval default to schema init**

In `bot/db.py`, add inside the `executescript` block after the `stops_preference` INSERT:

```python
INSERT OR IGNORE INTO config (key, value) VALUES ('scan_interval', '1440');
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_init_creates_scan_interval_config -v`
Expected: PASS

- [ ] **Step 5: Write failing test for scan_interval column migration**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_routes_have_scan_interval_column(db):
    route_id = await db.add_route("ATQ", "BOM")
    routes = await db.get_active_routes()
    assert routes[0]["scan_interval"] is None
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_routes_have_scan_interval_column -v`
Expected: FAIL — `KeyError: 'scan_interval'`

- [ ] **Step 7: Add scan_interval column migration and update get_active_routes**

In `bot/db.py`, add after the existing `max_stops` migration block (after line 57):

```python
# Migrate: add scan_interval column if missing
try:
    await self.db.execute("ALTER TABLE routes ADD COLUMN scan_interval TEXT DEFAULT NULL")
    await self.db.commit()
except Exception:
    pass  # Column already exists
```

In `bot/db.py`, update the `get_active_routes` SELECT to include `scan_interval`:

```python
async def get_active_routes(self) -> list[dict]:
    cursor = await self.db.execute(
        "SELECT id, from_airport, to_airport, max_stops, scan_interval FROM routes WHERE is_active = 1"
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_routes_have_scan_interval_column -v`
Expected: PASS

- [ ] **Step 9: Run all existing tests to verify no regressions**

Run: `pytest tests/test_db.py -v`
Expected: all PASS

- [ ] **Step 10: Commit**

```bash
git add bot/db.py tests/test_db.py
git commit -m "feat: add scan_interval to DB schema with migration"
```

---

### Task 3: DB methods — set_route_scan_interval, get_route_scan_interval

**Files:**
- Modify: `bot/db.py` (add methods after `get_route_stops_preference`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing test for set_route_scan_interval**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_set_route_scan_interval(db):
    route_id = await db.add_route("ATQ", "BOM")
    updated = await db.set_route_scan_interval(route_id, "120")
    assert updated is True
    routes = await db.get_active_routes()
    assert routes[0]["scan_interval"] == "120"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_set_route_scan_interval -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'set_route_scan_interval'`

- [ ] **Step 3: Implement set_route_scan_interval**

Add to `bot/db.py` after `get_route_stops_preference`:

```python
async def set_route_scan_interval(self, route_id: int, interval: str) -> bool:
    valid = {"60", "120", "240", "360", "720", "1440"}
    if interval not in valid:
        return False
    cursor = await self.db.execute(
        "UPDATE routes SET scan_interval = ? WHERE id = ? AND is_active = 1",
        (interval, route_id),
    )
    await self.db.commit()
    return cursor.rowcount > 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_set_route_scan_interval -v`
Expected: PASS

- [ ] **Step 5: Write failing test for set_route_scan_interval with invalid value**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_set_route_scan_interval_invalid(db):
    route_id = await db.add_route("ATQ", "BOM")
    updated = await db.set_route_scan_interval(route_id, "45")
    assert updated is False
    routes = await db.get_active_routes()
    assert routes[0]["scan_interval"] is None
```

- [ ] **Step 6: Run test to verify it passes (already handled by validation)**

Run: `pytest tests/test_db.py::test_set_route_scan_interval_invalid -v`
Expected: PASS

- [ ] **Step 7: Write failing test for set_route_scan_interval on nonexistent route**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_set_route_scan_interval_nonexistent(db):
    updated = await db.set_route_scan_interval(999, "120")
    assert updated is False
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_set_route_scan_interval_nonexistent -v`
Expected: PASS

- [ ] **Step 9: Write failing test for get_route_scan_interval with per-route value**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_get_route_scan_interval_per_route(db):
    route_id = await db.add_route("ATQ", "BOM")
    await db.set_route_scan_interval(route_id, "120")
    interval = await db.get_route_scan_interval(route_id)
    assert interval == 120
```

- [ ] **Step 10: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_get_route_scan_interval_per_route -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'get_route_scan_interval'`

- [ ] **Step 11: Implement get_route_scan_interval**

Add to `bot/db.py` after `set_route_scan_interval`:

```python
async def get_route_scan_interval(self, route_id: int) -> int:
    """Return effective scan interval in minutes for a route."""
    cursor = await self.db.execute(
        "SELECT scan_interval FROM routes WHERE id = ?", (route_id,)
    )
    row = await cursor.fetchone()
    if row and row["scan_interval"]:
        return int(row["scan_interval"])
    global_interval = await self.get_config("scan_interval")
    return int(global_interval) if global_interval else 1440
```

- [ ] **Step 12: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_get_route_scan_interval_per_route -v`
Expected: PASS

- [ ] **Step 13: Write failing test for get_route_scan_interval fallback to global**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_get_route_scan_interval_falls_back_to_global(db):
    route_id = await db.add_route("ATQ", "BOM")
    interval = await db.get_route_scan_interval(route_id)
    assert interval == 1440  # default global
```

- [ ] **Step 14: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_get_route_scan_interval_falls_back_to_global -v`
Expected: PASS

- [ ] **Step 15: Write failing test for get_route_scan_interval with custom global**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_get_route_scan_interval_custom_global(db):
    route_id = await db.add_route("ATQ", "BOM")
    await db.set_config("scan_interval", "360")
    interval = await db.get_route_scan_interval(route_id)
    assert interval == 360
```

- [ ] **Step 16: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_get_route_scan_interval_custom_global -v`
Expected: PASS

- [ ] **Step 17: Run all DB tests**

Run: `pytest tests/test_db.py -v`
Expected: all PASS

- [ ] **Step 18: Commit**

```bash
git add bot/db.py tests/test_db.py
git commit -m "feat: add set/get_route_scan_interval DB methods with validation"
```

---

### Task 4: Price history upsert

**Files:**
- Modify: `bot/db.py:32-43` (schema — add unique index), `bot/db.py:117-133` (save_price_history)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing test for price history upsert**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_save_price_history_upserts_same_day(db):
    route_id = await db.add_route("ATQ", "BOM")
    # First save
    await db.save_price_history(
        route_id=route_id,
        scan_date="2026-03-07",
        cheapest_travel_date="2026-03-18",
        cheapest_price=3200.0,
        cheapest_airline="IndiGo",
        avg_price=5200.0,
        price_data=None,
    )
    # Second save same day — should overwrite, not duplicate
    await db.save_price_history(
        route_id=route_id,
        scan_date="2026-03-07",
        cheapest_travel_date="2026-03-20",
        cheapest_price=2900.0,
        cheapest_airline="SpiceJet",
        avg_price=4800.0,
        price_data=None,
    )
    history = await db.get_price_history(route_id, days=7)
    assert len(history) == 1
    assert history[0]["cheapest_price"] == 2900.0
    assert history[0]["cheapest_airline"] == "SpiceJet"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_save_price_history_upserts_same_day -v`
Expected: FAIL — `assert 2 == 1` (two rows for the same date)

- [ ] **Step 3: Add unique index and change INSERT to INSERT OR REPLACE**

In `bot/db.py`, add inside the `executescript` block after the `price_history` table creation:

```python
CREATE UNIQUE INDEX IF NOT EXISTS idx_price_history_route_date
ON price_history(route_id, scan_date);
```

In `bot/db.py`, change the `save_price_history` method's SQL from `INSERT INTO` to `INSERT OR REPLACE INTO`:

```python
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
        """INSERT OR REPLACE INTO price_history
        (route_id, scan_date, cheapest_travel_date, cheapest_price, cheapest_airline, avg_price, price_data)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (route_id, scan_date, cheapest_travel_date, cheapest_price, cheapest_airline, avg_price, price_data),
    )
    await self.db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_save_price_history_upserts_same_day -v`
Expected: PASS

- [ ] **Step 5: Run all DB tests to check no regressions**

Run: `pytest tests/test_db.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add bot/db.py tests/test_db.py
git commit -m "feat: upsert price history to prevent duplicate same-day entries"
```

---

## Chunk 2: Scheduling Layer

### Task 5: Replace schedule_daily_job with schedule_scan_jobs

**Files:**
- Modify: `bot/main.py:1-46`
- Modify: `bot/handlers.py:1-17` (add `_scheduled_scan_route`), `bot/handlers.py:298-316` (conditional retry), `bot/handlers.py:345-356` (remove `daily_scan_job`)

- [ ] **Step 1: Add _scheduled_scan_route callback to handlers.py**

Add after `_retry_scan_job` (around line 343), replacing `daily_scan_job`:

```python
async def _scheduled_scan_route(context: ContextTypes.DEFAULT_TYPE):
    """Repeating job callback for a single route."""
    is_paused = await db.get_config("is_paused")
    if is_paused == "1":
        return

    route = context.job.data
    if not route:
        return

    scanning = context.bot_data.setdefault("_scanning_routes", set())
    if route["id"] in scanning:
        return
    scanning.add(route["id"])
    try:
        await _scan_and_send(context, route)
    finally:
        scanning.discard(route["id"])
```

Remove the old `daily_scan_job` function (lines 345-356).

- [ ] **Step 2: Update conditional retry logic and error message in _scan_and_send**

In `bot/handlers.py`, find the failure block inside `_scan_and_send` where `result is None` and `is_retry` is False (the block that calls `format_error_message` and schedules a retry). Replace that `else` block with:

```python
else:
    # Schedule retry only if interval > 4 hours
    interval = await db.get_route_scan_interval(route["id"])
    if interval > 240:
        msg = format_error_message(from_code, to_code)
        await context.bot.send_message(chat_id=CHAT_ID, text=msg)
        context.job_queue.run_once(
            _retry_scan_job,
            when=4 * 60 * 60,
            data=route,
            name=f"retry_{route['id']}",
        )
    else:
        msg = (
            f"⚠️ {from_code} → {to_code}\n"
            "Scan failed. Will retry on next scheduled scan.\n"
            "Run /check to try manually."
        )
        await context.bot.send_message(chat_id=CHAT_ID, text=msg)
```

- [ ] **Step 3: Rewrite schedule_scan_jobs in main.py**

Remove the entire `schedule_daily_job` function and its `DAILY_JOB_NAME` constant from `bot/main.py`. Replace with:

```python
from datetime import datetime, time as dt_time, timedelta


SCAN_JOB_PREFIX = "scan_route_"


async def schedule_scan_jobs(application: Application):
    """Schedule or reschedule per-route scan jobs."""
    # Remove all existing scan jobs (.jobs() available in python-telegram-bot>=21.0)
    for job in application.job_queue.jobs():
        if job.name and job.name.startswith(SCAN_JOB_PREFIX):
            job.schedule_removal()

    notify_time = await handlers.db.get_config("notify_time")
    hour, minute = map(int, notify_time.split(":"))
    tz = ZoneInfo(TIMEZONE)

    routes = await handlers.db.get_active_routes()
    for route in routes:
        interval_minutes = await handlers.db.get_route_scan_interval(route["id"])
        interval_secs = interval_minutes * 60

        now = datetime.now(tz)
        today_notify = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if now < today_notify:
            first = today_notify - now
        else:
            elapsed = (now - today_notify).total_seconds()
            slots_passed = int(elapsed // interval_secs)
            next_slot = today_notify + timedelta(seconds=(slots_passed + 1) * interval_secs)
            first = next_slot - now
            if first.total_seconds() > interval_secs:
                first = timedelta(seconds=0)

        application.job_queue.run_repeating(
            handlers._scheduled_scan_route,
            interval=interval_secs,
            first=first,
            data=route,
            name=f"{SCAN_JOB_PREFIX}{route['id']}",
        )

    logger.info(
        f"Scheduled {len(routes)} route scan jobs (notify_time={notify_time} {TIMEZONE})"
    )
```

- [ ] **Step 4: Update post_init to call schedule_scan_jobs**

In `bot/main.py`, update `post_init`:

```python
async def post_init(application: Application):
    """Called after bot is initialized."""
    db = Database()
    await db.init()
    handlers.db = db
    await schedule_scan_jobs(application)
    logger.info("SastaFlight bot started")
```

- [ ] **Step 5: Update /time command to use schedule_scan_jobs**

In `bot/handlers.py`, find the `time_command` function. It contains a deferred import `from bot.main import schedule_daily_job` and a call `await schedule_daily_job(context.application)`. Replace both lines with:

```python
from bot.main import schedule_scan_jobs
await schedule_scan_jobs(context.application)
```

- [ ] **Step 6: Schedule scan job when route is added via /add**

In `bot/handlers.py`, find the `add_command` function. After the route is added and the stops keyboard is sent, schedule a scan job for the new route. Add before the `await update.message.reply_text(...)` call:

```python
# Schedule a scan job for the new route
from bot.main import schedule_scan_jobs
await schedule_scan_jobs(context.application)
```

Note: This reschedules all routes rather than scheduling just the new one. This is a deliberate simplification — the spec suggests per-route scheduling but full reschedule is simpler and correct. Individual rescheduling can be optimized later if needed.

- [ ] **Step 7: Run all tests to verify no regressions**

Run: `pytest tests/ -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add bot/main.py bot/handlers.py
git commit -m "feat: replace daily job with per-route repeating scan jobs"
```

---

### Task 5b: Scheduling and callback tests

**Files:**
- Test: `tests/test_handlers.py` (new file)

- [ ] **Step 1: Write test for _scheduled_scan_route pause check**

Create `tests/test_handlers.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_scheduled_scan_route_skips_when_paused():
    """_scheduled_scan_route should do nothing when is_paused is '1'."""
    from bot.handlers import _scheduled_scan_route

    mock_context = MagicMock()
    mock_context.bot_data = {}
    mock_context.job.data = {"id": 1, "from_airport": "ATQ", "to_airport": "BOM"}

    with patch("bot.handlers.db") as mock_db, \
         patch("bot.handlers._scan_and_send") as mock_scan:
        mock_db.get_config = AsyncMock(return_value="1")
        await _scheduled_scan_route(mock_context)
        mock_scan.assert_not_called()


@pytest.mark.asyncio
async def test_scheduled_scan_route_scans_when_not_paused():
    """_scheduled_scan_route should call _scan_and_send when not paused."""
    from bot.handlers import _scheduled_scan_route

    route = {"id": 1, "from_airport": "ATQ", "to_airport": "BOM"}
    mock_context = MagicMock()
    mock_context.bot_data = {}
    mock_context.job.data = route

    with patch("bot.handlers.db") as mock_db, \
         patch("bot.handlers._scan_and_send", new_callable=AsyncMock) as mock_scan:
        mock_db.get_config = AsyncMock(return_value="0")
        await _scheduled_scan_route(mock_context)
        mock_scan.assert_called_once_with(mock_context, route)


@pytest.mark.asyncio
async def test_scheduled_scan_route_skips_concurrent_scan():
    """_scheduled_scan_route should skip if route is already being scanned."""
    from bot.handlers import _scheduled_scan_route

    route = {"id": 1, "from_airport": "ATQ", "to_airport": "BOM"}
    mock_context = MagicMock()
    mock_context.bot_data = {"_scanning_routes": {1}}  # Already scanning
    mock_context.job.data = route

    with patch("bot.handlers.db") as mock_db, \
         patch("bot.handlers._scan_and_send", new_callable=AsyncMock) as mock_scan:
        mock_db.get_config = AsyncMock(return_value="0")
        await _scheduled_scan_route(mock_context)
        mock_scan.assert_not_called()


@pytest.mark.asyncio
async def test_conditional_retry_skipped_for_short_interval():
    """_scan_and_send should NOT schedule retry when interval <= 4h."""
    from bot.handlers import _scan_and_send

    route = {"id": 1, "from_airport": "ATQ", "to_airport": "BOM"}
    mock_context = MagicMock()
    mock_context.bot.send_message = AsyncMock()
    mock_context.job_queue.run_once = MagicMock()

    with patch("bot.handlers.db") as mock_db, \
         patch("bot.handlers.scan_route", new_callable=AsyncMock, return_value=None):
        mock_db.get_route_stops_preference = AsyncMock(return_value="any")
        mock_db.get_route_scan_interval = AsyncMock(return_value=120)  # 2h
        await _scan_and_send(mock_context, route)
        mock_context.job_queue.run_once.assert_not_called()


@pytest.mark.asyncio
async def test_conditional_retry_scheduled_for_long_interval():
    """_scan_and_send should schedule retry when interval > 4h."""
    from bot.handlers import _scan_and_send

    route = {"id": 1, "from_airport": "ATQ", "to_airport": "BOM"}
    mock_context = MagicMock()
    mock_context.bot.send_message = AsyncMock()
    mock_context.job_queue.run_once = MagicMock()

    with patch("bot.handlers.db") as mock_db, \
         patch("bot.handlers.scan_route", new_callable=AsyncMock, return_value=None):
        mock_db.get_route_stops_preference = AsyncMock(return_value="any")
        mock_db.get_route_scan_interval = AsyncMock(return_value=720)  # 12h
        await _scan_and_send(mock_context, route)
        mock_context.job_queue.run_once.assert_called_once()
```

- [ ] **Step 2: Run new handler tests**

Run: `pytest tests/test_handlers.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_handlers.py
git commit -m "test: add tests for scheduled scan callback and conditional retry"
```

---

## Chunk 3: User Interface

### Task 6: /frequency command — global scan interval

**Files:**
- Modify: `bot/handlers.py` (add frequency_command, frequency_callback)
- Modify: `bot/main.py` (register handlers)

- [ ] **Step 1: Add INTERVAL_LABELS helper to handlers.py**

Add after the `STOPS_LABELS` dict:

```python
from bot.config import INTERVAL_OPTIONS

INTERVAL_LABELS = {str(v): k for k, v in INTERVAL_OPTIONS.items()}  # {"60": "1h", ...}


def _frequency_keyboard(callback_prefix: str, current_minutes: str | None = None) -> InlineKeyboardMarkup:
    """Build inline keyboard for frequency selection."""
    buttons = []
    for label, minutes in INTERVAL_OPTIONS.items():
        display = f">> {label} <<" if str(minutes) == current_minutes else label
        buttons.append(InlineKeyboardButton(display, callback_data=f"{callback_prefix}:{minutes}"))
    return InlineKeyboardMarkup([buttons[:3], buttons[3:]])
```

- [ ] **Step 2: Add frequency_command handler**

Add to `bot/handlers.py`:

```python
async def frequency_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    current = await db.get_config("scan_interval") or "1440"
    label = INTERVAL_LABELS.get(current, f"{current}m")
    keyboard = _frequency_keyboard("freq_global", current)
    await update.message.reply_text(
        f"Current scan frequency: every {label}\n"
        "Select new frequency:",
        reply_markup=keyboard,
    )
```

- [ ] **Step 3: Add frequency_callback handler**

Add to `bot/handlers.py`:

```python
async def frequency_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks for frequency."""
    if not _is_authorized(update):
        return
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("freq_global:"):
        value = data.split(":")[1]
        if value not in INTERVAL_LABELS:
            return
        await db.set_config("scan_interval", value)

        from bot.main import schedule_scan_jobs
        await schedule_scan_jobs(context.application)

        label = INTERVAL_LABELS[value]
        await query.edit_message_text(f"✅ Scan frequency set to every {label} for all routes.")

    elif data.startswith("freq_pick:"):
        try:
            route_id = int(data.split(":")[1])
        except (ValueError, IndexError):
            return
        routes = await db.get_active_routes()
        route = next((r for r in routes if r["id"] == route_id), None)
        if route:
            current = route.get("scan_interval")
            keyboard = _frequency_keyboard(f"freq_route:{route_id}", current)
            await query.edit_message_text(
                f"Select scan frequency for {route['from_airport']} → {route['to_airport']}:",
                reply_markup=keyboard,
            )

    elif data.startswith("freq_route:"):
        parts = data.split(":")
        try:
            route_id = int(parts[1])
        except (ValueError, IndexError):
            return
        value = parts[2] if len(parts) > 2 else None
        if value not in INTERVAL_LABELS:
            return
        await db.set_route_scan_interval(route_id, value)

        from bot.main import schedule_scan_jobs
        await schedule_scan_jobs(context.application)

        routes = await db.get_active_routes()
        route = next((r for r in routes if r["id"] == route_id), None)
        label = INTERVAL_LABELS[value]
        if route:
            await query.edit_message_text(
                f"✅ Scan frequency for {route['from_airport']} → {route['to_airport']} set to every {label}."
            )
        else:
            await query.edit_message_text(f"✅ Route scan frequency set to every {label}.")
```

- [ ] **Step 4: Register handlers in main.py**

In `bot/main.py`, add inside `main()`:

```python
application.add_handler(CommandHandler("frequency", handlers.frequency_command))
application.add_handler(CallbackQueryHandler(handlers.frequency_callback, pattern=r"^freq_"))
```

- [ ] **Step 5: Run all tests to verify no regressions**

Run: `pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add bot/handlers.py bot/main.py
git commit -m "feat: add /frequency command for global scan interval"
```

---

### Task 7: Per-route frequency in /routes display

**Files:**
- Modify: `bot/handlers.py` (routes_command)

- [ ] **Step 1: Update routes_command to show frequency and add Change Frequency button**

In `bot/handlers.py`, replace the `routes_command` function:

```python
async def routes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    routes = await db.get_active_routes()
    if not routes:
        await update.message.reply_text("No active routes. Use /add to add one.")
        return

    global_pref = await db.get_config("stops_preference") or "any"
    global_interval = await db.get_config("scan_interval") or "1440"
    lines = ["📋 Active Routes:\n"]
    keyboard_rows = []
    for r in routes:
        effective_stops = r["max_stops"] or global_pref
        stops_label = STOPS_LABELS.get(effective_stops, effective_stops)
        effective_interval = r["scan_interval"] or global_interval
        freq_label = INTERVAL_LABELS.get(effective_interval, f"{effective_interval}m")
        lines.append(f"  {r['id']}. {r['from_airport']} → {r['to_airport']} | {stops_label} | Every {freq_label}")
        keyboard_rows.append([
            InlineKeyboardButton(
                f"Change Stops: {r['from_airport']} → {r['to_airport']}",
                callback_data=f"stops_pick:{r['id']}",
            )
        ])
        keyboard_rows.append([
            InlineKeyboardButton(
                f"Change Frequency: {r['from_airport']} → {r['to_airport']}",
                callback_data=f"freq_pick:{r['id']}",
            )
        ])

    markup = InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None
    await update.message.reply_text("\n".join(lines), reply_markup=markup)
```

- [ ] **Step 2: Run all tests to verify no regressions**

Run: `pytest tests/ -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add bot/handlers.py
git commit -m "feat: show frequency in /routes and add per-route change button"
```

---

### Task 8: Update help text, /time text, error messages, and /remove job cancellation

**Files:**
- Modify: `bot/handlers.py` (start_command, time_command, remove_command)
- Modify: `bot/formatter.py` (format_retry_failed_message)

- [ ] **Step 1: Add /frequency to help text**

In `bot/handlers.py`, update `start_command` to include the frequency line. Add after the `/stops` line:

```python
"/frequency - Set scan frequency\n"
```

- [ ] **Step 2: Update /time command user-facing text**

In `bot/handlers.py`, find the `time_command` function. Update the response strings:
- Change `"Current scan time: {current} IST"` to `"Current scan start time: {current} IST"`
- Change `"✅ Daily scan time set to {time_str} IST"` to `"✅ Scan start time set to {time_str} IST"`

- [ ] **Step 3: Fix retry-failed message in handlers.py and formatter.py**

The "Will try again tomorrow" message is hardcoded inline in `bot/handlers.py` inside `_scan_and_send` (the `if is_retry:` block). Update it to use the formatter function and fix the wording.

In `bot/handlers.py`, add `format_retry_failed_message` to the imports from `bot.formatter`:

```python
from bot.formatter import (
    format_daily_message,
    format_error_message,
    format_history_message,
    format_retry_failed_message,
)
```

Then replace the inline retry-failed message block in `_scan_and_send` (the `if is_retry:` branch) with:

```python
if is_retry:
    msg = format_retry_failed_message(from_code, to_code)
    await context.bot.send_message(chat_id=CHAT_ID, text=msg)
```

In `bot/formatter.py`, update `format_retry_failed_message`:

```python
def format_retry_failed_message(from_airport: str, to_airport: str) -> str:
    return (
        f"❌ {from_airport} → {to_airport}\n"
        "Scan failed after retry. Will try again on next scheduled scan.\n"
        "Run /check to try manually."
    )
```

- [ ] **Step 5: Update remove_command to cancel scheduled job**

In `bot/handlers.py`, update `remove_command`. After the `removed = await db.remove_route(route_id)` check succeeds, cancel the job:

```python
if removed:
    # Cancel the scheduled scan job for this route
    from bot.main import SCAN_JOB_PREFIX
    for job in context.job_queue.get_jobs_by_name(f"{SCAN_JOB_PREFIX}{route_id}"):
        job.schedule_removal()
    await update.message.reply_text(f"✅ Route {route_id} removed.")
```

- [ ] **Step 6: Run all tests**

Run: `pytest tests/ -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add bot/handlers.py bot/formatter.py
git commit -m "feat: update help text, /time text, error messages, and cancel job on route removal"
```

---

## Chunk 4: Final Verification

### Task 9: Full integration check

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v`
Expected: all PASS

- [ ] **Step 2: Verify bot starts without errors**

Run: `python -c "from bot.main import main; print('Import OK')"`
Expected: `Import OK`

- [ ] **Step 3: Verify all new imports resolve**

Run: `python -c "from bot.config import INTERVAL_OPTIONS; from bot.handlers import frequency_command, frequency_callback, _scheduled_scan_route; from bot.main import schedule_scan_jobs, SCAN_JOB_PREFIX; print('All imports OK')"`
Expected: `All imports OK`
