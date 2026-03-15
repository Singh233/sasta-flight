# Configurable Scan Frequency

## Purpose

Allow users to set how often routes are scanned, from every 1 hour up to once daily. The primary goal is catching flight price drops quickly by enabling more frequent monitoring.

## Approach

Replace the single `run_daily()` job with per-route `run_repeating()` jobs from `python-telegram-bot`'s JobQueue. Each route gets its own repeating job with a configurable interval.

## Data Model

### Config table (global default)

New key: `scan_interval`
- Stores interval in minutes as a string (e.g., `"60"`, `"120"`, `"1440"`)
- Default: `"1440"` (24 hours — preserves current once-daily behavior)

### Routes table (per-route override)

New column: `scan_interval`
- Type: `TEXT DEFAULT NULL`
- `NULL` means use global default
- Valid values: `60`, `120`, `240`, `360`, `720`, `1440`
- Migration SQL: `ALTER TABLE routes ADD COLUMN scan_interval TEXT DEFAULT NULL`
- Validation: DB setter must reject values not in the valid set

### Resolution logic

Same pattern as `stops_preference`:
1. Route-level `scan_interval` if set
2. Else global `scan_interval` from config table
3. Else `1440` (fallback default)

DB method signature:
```python
async def get_route_scan_interval(route_id: int) -> int:
    """Return effective scan interval in minutes for a route."""
```

### Constants (config.py)

```python
INTERVAL_OPTIONS = {"1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "24h": 1440}
```

## Scheduling Architecture

### Startup

`schedule_daily_job()` becomes `schedule_scan_jobs()`:
1. Fetch all active routes
2. For each route, resolve its effective interval
3. Schedule a `run_repeating()` job named `scan_route_{id}`
4. Calculate `first` parameter (see below)

### `first` parameter calculation

Use `timedelta` for `first`. Compute the next aligned scan time from `notify_time`:

```python
now = datetime.now(tz)
today_notify = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

if now < today_notify:
    # notify_time hasn't passed yet — first scan at notify_time
    first = today_notify - now
else:
    # notify_time has passed — find next aligned slot
    elapsed = (now - today_notify).total_seconds()
    interval_secs = interval_minutes * 60
    slots_passed = int(elapsed // interval_secs)
    next_slot = today_notify + timedelta(seconds=(slots_passed + 1) * interval_secs)
    first = next_slot - now
    # If next_slot is more than interval away (shouldn't happen), cap it
    if first.total_seconds() > interval_secs:
        first = timedelta(seconds=0)  # fire immediately
```

This ensures scans align to `notify_time` slots (e.g., notify_time=08:00, interval=2h → scans at 08:00, 10:00, 12:00...).

### Per-route scan callback

Each route's repeating job calls a new `_scheduled_scan_route()` function:

```python
async def _scheduled_scan_route(context: ContextTypes.DEFAULT_TYPE):
    """Repeating job callback for a single route."""
    # Check global pause
    is_paused = await db.get_config("is_paused")
    if is_paused == "1":
        return

    route = context.job.data  # route dict passed as job data

    # Scan lock: skip if this route is already being scanned
    scanning = context.bot_data.setdefault("_scanning_routes", set())
    if route["id"] in scanning:
        return
    scanning.add(route["id"])
    try:
        await _scan_and_send(context, route)
    finally:
        scanning.discard(route["id"])
```

Key points:
- **`is_paused` check** is in the per-route callback (not in a parent loop like before)
- **Scan lock** via `bot_data["_scanning_routes"]` set prevents concurrent scans of the same route (e.g., if a scan takes longer than the interval)

### Rescheduling triggers

- Global frequency change: reschedule all routes without a per-route override
- Per-route frequency change: reschedule only that route's job
- `notify_time` change: reschedule all jobs with recalculated `first`
- Route added: schedule a new job for that route
- Route removed: cancel that route's job

### Retry behavior

With frequent scans (1-4h), the existing 4-hour retry becomes redundant since the next scheduled scan will likely fire before or around the same time as the retry. New logic:
- Only schedule a retry if the route's interval is > 4 hours (i.e., 6h, 12h, 24h)
- For intervals <= 4h, the next scheduled scan serves as the natural retry

### Bot restart

Jobs are re-created from DB state on startup. The `first` calculation handles the case where `notify_time` has already passed by finding the next aligned slot.

## User Interface

### `/frequency` command

- No arguments: shows current global frequency + inline keyboard
- Inline keyboard options: `1h` | `2h` | `4h` | `6h` | `12h` | `24h`
- Selecting an option updates global `scan_interval` and reschedules affected routes
- Feedback: `"Scan frequency set to every 2h for all routes."`

### Per-route override via `/routes`

- Add a `[Change Frequency]` button to each route's entry (alongside existing `[Change Stops]`)
- Tapping shows the same 6-option inline keyboard
- Selecting sets that route's `scan_interval` and reschedules only that job
- Feedback: `"Scan frequency for DEL → GOA set to every 1h."`

### Route display in `/routes`

Show effective frequency alongside other settings:
`"DEL → GOA | Stops: any | Frequency: 2h"`

### `/add` command

No frequency prompt during route creation. New routes inherit the global default. Users can override per-route frequency later via `/routes` → `[Change Frequency]`. This avoids complicating the add flow with a multi-step conversation.

### `/help` update

Add `/frequency` to the help text listing all available commands.

## Impact on Existing Features

### `/pause` and `/resume`

The per-route callback checks `is_paused` on every invocation (see scan callback above). No changes needed to pause/resume commands themselves.

### `/check` (manual scan)

No change. Independent one-off scan.

### `/time` command

When `notify_time` changes, all repeating jobs are rescheduled with `first` recalculated. Uses the same circular import pattern (`from bot.main import schedule_scan_jobs`) as the current `schedule_daily_job` reference.

### Price history

With multiple scans per day, `save_price_history` should **upsert** (UPDATE on conflict) rather than INSERT for same-day entries. This keeps one history row per route per day (the latest scan result), preserving the 7-day trend display without data explosion.

Implementation: use `INSERT OR REPLACE` keyed on `(route_id, scan_date)` so that subsequent scans on the same day overwrite the previous entry.

### `/remove` command

Explicitly cancel the route's scheduled job on deactivation.

## Valid interval values

| Label | Minutes | Scans/day |
|-------|---------|-----------|
| 1h    | 60      | 24        |
| 2h    | 120     | 12        |
| 4h    | 240     | 6         |
| 6h    | 360     | 4         |
| 12h   | 720     | 2         |
| 24h   | 1440    | 1         |

## Rate-limiting note

At 1h frequency with multiple routes, each scan makes API calls to Google Flights. Users should be aware that very frequent scans across many routes may trigger rate-limiting. The default remains 24h to be conservative.

## Files to modify

- `bot/config.py` — add `INTERVAL_OPTIONS` constant
- `bot/db.py` — add `scan_interval` to schema init, migration (`ALTER TABLE`), `get_route_scan_interval()` resolver, setter with validation, upsert for `save_price_history`
- `bot/handlers.py` — add `/frequency` command + callback, per-route frequency callback in `/routes`, update `/routes` display, add `_scheduled_scan_route()` with pause check and scan lock, conditional retry logic, update `/help` text
- `bot/main.py` — replace `schedule_daily_job()` with `schedule_scan_jobs()` (per-route jobs), register `/frequency` handler
- `tests/` — update tests for new DB methods, scan callback, and scheduling logic
