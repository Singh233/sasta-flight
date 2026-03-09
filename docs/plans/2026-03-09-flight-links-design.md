# Flight Links in Messages — Design

## Goal

Add clickable Google Flights links to each of the Top N cheapest days in the daily scan message, so users can tap and go book directly.

## URL Format

Use Google Flights' `tfs` parameter (base64-encoded protobuf) to generate search URLs that open with:

- **One-way** trip type
- **Correct airports** (from/to)
- **Correct date**
- **Stops preference** matching the route's filter
- **Economy** seat, **1 adult**

URL: `https://www.google.com/travel/flights/search?tfs=<base64>`

## Protobuf Schema (from Google Flights)

```protobuf
message Airport { string airport = 2; }
message FlightData {
  string date = 2;
  optional int32 max_stops = 5;
  Airport from_flight = 13;
  Airport to_flight = 14;
}
enum Seat { ECONOMY = 1; }
enum Trip { ONE_WAY = 2; }
enum Passenger { ADULT = 1; }
message Info {
  repeated FlightData data = 3;
  repeated Passenger passengers = 8;
  Seat seat = 9;
  Trip trip = 19;
}
```

Stops mapping: `direct` → 1, `1stop` → 2, `2stops` → 3, `any` → omit field.

## Message Format Change

Before:
```
📊 Top 5 Cheapest Days:
 1. Mar 18 (Tue) - ₹3,200
 2. Mar 20 (Thu) - ₹3,450
```

After:
```
📊 Top 5 Cheapest Days:
 1. Mar 18 (Tue) - ₹3,200  Book →
 2. Mar 20 (Thu) - ₹3,450  Book →
```

Where `Book →` is a Telegram Markdown link.

## Files Changed

1. **`bot/formatter.py`** — Add `_flight_url()` helper, update `format_daily_message()` signature and top-days loop
2. **`bot/handlers.py`** — Pass `max_stops` to formatter, add `parse_mode="Markdown"` to scan result `send_message`
3. **`tests/test_formatter.py`** — Update tests for new format

## Constraints

- No new dependencies (manual protobuf encoding)
- No database changes
- Only Top N list gets links (not cheapest header, not history)
