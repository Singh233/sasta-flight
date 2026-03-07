# Stops Preference Feature Design

## Problem
Users cannot filter flights by number of stops. The bot returns the cheapest flight regardless of layovers, which may not match user preferences.

## Decision Summary
- Stops preference: global default + per-route override
- Options: Any, Direct, Up to 1 Stop, Up to 2 Stops (cumulative, matching Google Flights behavior)
- Default: Any (backward compatible)
- UX: Inline keyboards for selection (no syntax to remember)
- Filtering: At API level via `fli.MaxStops` enum + validate each top-N day with detail fetch (Approach B — accurate data over speed)
- Display: Active filter shown in scan result header

## Mapping

| User-facing label | Internal value | `fli.MaxStops` enum |
|---|---|---|
| Any | `any` | `MaxStops.ANY` |
| Direct | `direct` | `MaxStops.NON_STOP` |
| Up to 1 Stop | `1stop` | `MaxStops.ONE_STOP_OR_FEWER` |
| Up to 2 Stops | `2stops` | `MaxStops.TWO_OR_FEWER_STOPS` |

## Data Model

### `routes` table
Add column: `max_stops TEXT DEFAULT NULL`
- NULL means "use global default"
- Valid values: `any`, `direct`, `1stop`, `2stops`

### `config` table
New row: `stops_preference = 'any'` (global default)

### Resolution logic
1. Route's `max_stops` if set
2. Else global `stops_preference` config
3. Else `any`

## Scanner Changes

### `scan_flight_details(from_code, to_code, travel_date, max_stops)`
- Pass `max_stops` to `FlightSearchFilters(stops=...)`.
- Import `MaxStops` from `fli.models`.

### `scan_route(from_code, to_code, max_stops)`
- `scan_route_dates()` unchanged (calendar API doesn't support stops filter).
- For each date in the full sorted calendar, call `scan_flight_details()` with stops filter.
- Skip dates where no matching flight is found.
- Stop once we have `TOP_CHEAPEST` valid results or exhaust all dates.
- Worst case: up to 30 `SearchFlights` calls per route.

## Telegram UX

### `/stops` command (global default)
- Bot replies with inline keyboard: `[Any] [Direct] [Up to 1 Stop] [Up to 2 Stops]`
- Current preference highlighted/indicated in button text
- Callback: saves to config, confirms with message

### `/add <FROM> <TO>` command (per-route on creation)
- After adding route, bot replies with inline keyboard for stops preference
- If user ignores keyboard, route uses global default (NULL)

### `/routes` command (per-route override)
- Each route in the list shows its effective stops preference
- Each route gets a `[Change Stops]` inline button
- Tapping shows the 4-option keyboard
- Confirms update

### Callback data format
- `stops_global:<value>` for global preference
- `stops_route:<route_id>:<value>` for per-route

## Formatter Changes
- Header gains filter label when not "Any": `✈️ ATQ → BOM | Next 30 Days | Filter: Direct`
- "Any" shows no filter label (clean default)

## DB Migration
- Use `ALTER TABLE routes ADD COLUMN max_stops TEXT DEFAULT NULL`
- Run in `Database.init()` with try/except for idempotency (column may already exist)
- Insert default config: `INSERT OR IGNORE INTO config (key, value) VALUES ('stops_preference', 'any')`
