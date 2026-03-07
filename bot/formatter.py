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


def format_daily_message(result: ScanResult, prev_cheapest: float | None = None, stops_label: str | None = None) -> str:
    header = f"✈️ {result.from_airport} → {result.to_airport} | Next 30 Days"
    if stops_label:
        header += f" | Filter: {stops_label}"
    lines = [
        header,
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
