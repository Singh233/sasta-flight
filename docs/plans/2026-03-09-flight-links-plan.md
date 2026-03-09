# Flight Links in Messages — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add clickable Google Flights `[Book →]` links to each Top N day in the daily scan message.

**Architecture:** Build a `_flight_url()` helper in `formatter.py` that manually encodes a protobuf message (one-way, economy, 1 adult, airports, date, stops) into base64 and constructs a Google Flights search URL. Update `format_daily_message()` to append Markdown links. Switch `send_message` to `parse_mode="Markdown"`.

**Tech Stack:** Python stdlib only (`struct`-free manual protobuf encoding + `base64`)

---

### Task 1: Add `_flight_url` helper with tests

**Files:**
- Modify: `bot/formatter.py`
- Modify: `tests/test_formatter.py`

**Step 1: Write the failing tests**

Add to `tests/test_formatter.py`:

```python
from bot.formatter import _flight_url


def test_flight_url_contains_base_url():
    url = _flight_url("ATQ", "BOM", "2026-03-18")
    assert url.startswith("https://www.google.com/travel/flights/search?tfs=")


def test_flight_url_differs_by_date():
    url1 = _flight_url("ATQ", "BOM", "2026-03-18")
    url2 = _flight_url("ATQ", "BOM", "2026-03-20")
    assert url1 != url2


def test_flight_url_differs_by_stops():
    url_any = _flight_url("ATQ", "BOM", "2026-03-18")
    url_direct = _flight_url("ATQ", "BOM", "2026-03-18", max_stops="direct")
    assert url_any != url_direct


def test_flight_url_no_stops_same_as_any():
    url_none = _flight_url("ATQ", "BOM", "2026-03-18")
    url_any = _flight_url("ATQ", "BOM", "2026-03-18", max_stops="any")
    assert url_none == url_any
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_formatter.py::test_flight_url_contains_base_url -v`
Expected: FAIL — `_flight_url` does not exist yet.

**Step 3: Implement `_flight_url` in `bot/formatter.py`**

Add at the top of `bot/formatter.py`:

```python
import base64
```

Add the helper function (after the existing `_format_stops` function, before `format_daily_message`):

```python
# Google Flights protobuf field encoding helpers
def _pb_varint(value: int) -> bytes:
    """Encode an integer as a protobuf varint."""
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def _pb_tag(field_number: int, wire_type: int) -> bytes:
    """Encode a protobuf field tag."""
    return _pb_varint((field_number << 3) | wire_type)


def _pb_string(field_number: int, value: str) -> bytes:
    """Encode a string field."""
    encoded = value.encode("utf-8")
    return _pb_tag(field_number, 2) + _pb_varint(len(encoded)) + encoded


def _pb_message(field_number: int, data: bytes) -> bytes:
    """Encode a nested message field."""
    return _pb_tag(field_number, 2) + _pb_varint(len(data)) + data


def _pb_enum(field_number: int, value: int) -> bytes:
    """Encode an enum/int32 field."""
    return _pb_tag(field_number, 0) + _pb_varint(value)


# Mapping from bot stops preference to Google Flights protobuf max_stops values
_URL_STOPS_MAP = {
    "direct": 1,   # Nonstop only
    "1stop": 2,    # 1 stop or fewer
    "2stops": 3,   # 2 stops or fewer
}


def _flight_url(from_airport: str, to_airport: str, date: str, max_stops: str = "any") -> str:
    """Build a Google Flights search URL for a one-way flight."""
    # Airport messages: message Airport { string airport = 2; }
    from_ap = _pb_string(2, from_airport)
    to_ap = _pb_string(2, to_airport)

    # FlightData: date=2, max_stops=5, from_flight=13, to_flight=14
    flight_data = _pb_string(2, date)
    stops_val = _URL_STOPS_MAP.get(max_stops)
    if stops_val is not None:
        flight_data += _pb_enum(5, stops_val)
    flight_data += _pb_message(13, from_ap)
    flight_data += _pb_message(14, to_ap)

    # Info: data=3, passengers=8, seat=9, trip=19
    info = _pb_message(3, flight_data)
    info += _pb_enum(8, 1)   # ADULT
    info += _pb_enum(9, 1)   # ECONOMY
    info += _pb_enum(19, 2)  # ONE_WAY

    tfs = base64.urlsafe_b64encode(info).decode("ascii").rstrip("=")
    return f"https://www.google.com/travel/flights/search?tfs={tfs}"
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_formatter.py -k "test_flight_url" -v`
Expected: All 4 new tests PASS.

**Step 5: Commit**

```bash
git add bot/formatter.py tests/test_formatter.py
git commit -m "feat: add _flight_url helper for Google Flights search links"
```

---

### Task 2: Add Book links to daily message

**Files:**
- Modify: `bot/formatter.py`
- Modify: `tests/test_formatter.py`

**Step 1: Write the failing test**

Add to `tests/test_formatter.py`:

```python
def test_format_daily_message_contains_book_links():
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
        ],
        avg_price=5200,
        min_price=3200,
        max_price=8900,
    )
    msg = format_daily_message(result, max_stops="direct")
    assert "[Book →]" in msg
    assert "google.com/travel/flights" in msg
    # Each top day should have a link
    assert msg.count("[Book →]") == 2
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_formatter.py::test_format_daily_message_contains_book_links -v`
Expected: FAIL — `format_daily_message` does not accept `max_stops` and does not produce links.

**Step 3: Update `format_daily_message` in `bot/formatter.py`**

Change the function signature at line 25 from:
```python
def format_daily_message(result: ScanResult, prev_cheapest: float | None = None, stops_label: str | None = None) -> str:
```
to:
```python
def format_daily_message(result: ScanResult, prev_cheapest: float | None = None, stops_label: str | None = None, max_stops: str = "any") -> str:
```

Change the top-days loop (line 53-54) from:
```python
    for i, day in enumerate(result.top_days, 1):
        lines.append(f" {i}. {_format_date(day['date'])} - {_format_price(day['price'])}")
```
to:
```python
    for i, day in enumerate(result.top_days, 1):
        url = _flight_url(result.from_airport, result.to_airport, day["date"], max_stops=max_stops)
        lines.append(f" {i}. {_format_date(day['date'])} - {_format_price(day['price'])}  [Book →]({url})")
```

**Step 4: Run all formatter tests**

Run: `python -m pytest tests/test_formatter.py -v`
Expected: All tests PASS (existing tests unaffected since `max_stops` defaults to `"any"`).

**Step 5: Commit**

```bash
git add bot/formatter.py tests/test_formatter.py
git commit -m "feat: add Book links to top cheapest days in daily message"
```

---

### Task 3: Pass `max_stops` and enable Markdown in handlers

**Files:**
- Modify: `bot/handlers.py`

**Step 1: Update `_scan_and_send` to pass `max_stops` to formatter**

At line 335, change:
```python
    msg = format_daily_message(result, prev_cheapest=prev_cheapest, stops_label=stops_label)
```
to:
```python
    msg = format_daily_message(result, prev_cheapest=prev_cheapest, stops_label=stops_label, max_stops=max_stops)
```

**Step 2: Enable Markdown parsing on scan result messages**

At line 336, change:
```python
    await context.bot.send_message(chat_id=CHAT_ID, text=msg)
```
to:
```python
    await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
```

**Step 3: Run all tests**

Run: `python -m pytest -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add bot/handlers.py
git commit -m "feat: pass stops to formatter and enable Markdown for flight links"
```

---

### Task 4: Manual verification

**Step 1: Start the bot locally**

Run: `python -m bot.main`

**Step 2: Send `/check` in Telegram**

Expected: Daily scan message with clickable `Book →` links on each top day.

**Step 3: Tap a `Book →` link**

Expected: Opens Google Flights with:
- One-way selected
- Correct airports
- Correct date
- Stops filter matching the route's preference

**Step 4: Final commit if any fixes needed**
