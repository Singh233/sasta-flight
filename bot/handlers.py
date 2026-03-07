import json
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import CHAT_ID
from bot.db import Database
from bot.scanner import scan_route, NO_MATCHES
from bot.formatter import (
    format_daily_message,
    format_error_message,
    format_history_message,
)

logger = logging.getLogger(__name__)

# Global db reference, set in main.py
db: Database = None

STOPS_LABELS = {
    "any": "Any",
    "direct": "Direct",
    "1stop": "Up to 1 Stop",
    "2stops": "Up to 2 Stops",
}

def _stops_keyboard(callback_prefix: str, current: str | None = None) -> InlineKeyboardMarkup:
    """Build inline keyboard for stops selection."""
    buttons = []
    for value, label in STOPS_LABELS.items():
        display = f">> {label} <<" if value == current else label
        buttons.append(InlineKeyboardButton(display, callback_data=f"{callback_prefix}:{value}"))
    return InlineKeyboardMarkup([buttons])


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
        "/stops - Set default stops preference\n"
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
    keyboard = _stops_keyboard(f"stops_newroute:{route_id}")
    await update.message.reply_text(
        f"✅ Route added: {from_code} → {to_code} (ID: {route_id})\n"
        "Select stops preference for this route:",
        reply_markup=keyboard,
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


async def stops_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks for stops preference."""
    if not _is_authorized(update):
        return
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("stops_global:"):
        value = data.split(":")[1]
        if value not in STOPS_LABELS:
            return
        await db.set_config("stops_preference", value)
        await query.edit_message_text(f"✅ Default stops preference set to: {STOPS_LABELS[value]}")

    elif data.startswith("stops_route:"):
        parts = data.split(":")
        try:
            route_id = int(parts[1])
        except (ValueError, IndexError):
            return
        value = parts[2] if len(parts) > 2 else None
        if value not in STOPS_LABELS:
            return
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
        try:
            route_id = int(parts[1])
        except (ValueError, IndexError):
            return
        value = parts[2] if len(parts) > 2 else None
        if value not in STOPS_LABELS:
            return
        await db.set_route_stops(route_id, value)
        await query.edit_message_text(f"✅ Stops preference set to: {STOPS_LABELS[value]}")

    elif data.startswith("stops_pick:"):
        try:
            route_id = int(data.split(":")[1])
        except (ValueError, IndexError):
            return
        routes = await db.get_active_routes()
        route = next((r for r in routes if r["id"] == route_id), None)
        if route:
            current = route["max_stops"]
            keyboard = _stops_keyboard(f"stops_route:{route_id}", current)
            await query.edit_message_text(
                f"Select stops preference for {route['from_airport']} → {route['to_airport']}:",
                reply_markup=keyboard,
            )


async def _scan_and_send(context: ContextTypes.DEFAULT_TYPE, route: dict, is_retry: bool = False):
    """Scan a single route and send the result. Schedule retry on failure."""
    from_code = route["from_airport"]
    to_code = route["to_airport"]

    # Resolve stops preference
    max_stops = await db.get_route_stops_preference(route["id"])

    result = await scan_route(from_code, to_code, max_stops=max_stops)

    if result is NO_MATCHES:
        stops_label = STOPS_LABELS.get(max_stops, max_stops)
        msg = (
            f"✈️ {from_code} → {to_code}\n"
            f"No flights found matching filter: {stops_label}\n"
            "Try a less restrictive stops preference via /stops or /routes."
        )
        await context.bot.send_message(chat_id=CHAT_ID, text=msg)
        return

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
