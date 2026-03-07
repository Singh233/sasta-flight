import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

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
from fli.search import SearchDates, SearchFlights

from bot.config import DAYS_TO_SCAN, TOP_CHEAPEST

logger = logging.getLogger(__name__)

# Sentinel: scan found dates but no flights matched the stops filter.
# Distinct from None (which means the scan itself failed).
NO_MATCHES = "NO_MATCHES"

STOPS_MAP = {
    "any": MaxStops.ANY,
    "direct": MaxStops.NON_STOP,
    "1stop": MaxStops.ONE_STOP_OR_FEWER,
    "2stops": MaxStops.TWO_OR_FEWER_STOPS,
}


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
        return NO_MATCHES

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
