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
