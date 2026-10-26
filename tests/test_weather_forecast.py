import json
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from test_agent_policy import model_factory

from jarvis import productivity


@pytest.fixture
def weather_service(runtime, monkeypatch):
    runtime.config.update({"weather_location": "Fixture City", "timezone": "Europe/Rome"})
    clock = [datetime(2026, 3, 28, 11, tzinfo=UTC)]
    calls, state = [], {"offline": False, "limit": 16}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

    monkeypatch.setattr(productivity, "datetime", Clock)

    async def fetch(url, **kwargs):
        calls.append(url)
        if state["offline"]:
            raise ConnectionError("Synthetic provider outage")
        if "geocoding-api" in url:
            value = {"results": [{"name": "Fixture City", "latitude": 12, "longitude": 34}]}
        else:
            zone = runtime.config.settings.timezone
            first = clock[0].astimezone(ZoneInfo(zone)).date()
            size = state["limit"]
            value = {
                "timezone": zone,
                "current": {"time": clock[0].astimezone(ZoneInfo(zone)).isoformat(),
                            "temperature_2m": 99, "weather_code": 0},
                "current_units": {"temperature_2m": "°C"},
                "daily_units": {"temperature_2m_min": "°C", "precipitation_probability_max": "%"},
                "daily": {
                    "time": [(first + timedelta(days=i)).isoformat() for i in range(size)],
                    "temperature_2m_min": list(range(10, 10 + size)),
                    "temperature_2m_max": list(range(20, 20 + size)),
                    "weather_code": [61] * size,
                    "precipitation_probability_max": [70] * size,
                    "precipitation_sum": [2.5] * size,
                    "wind_speed_10m_max": [18] * size,
                },
            }
            if state.get("mutate"):
                state["mutate"](value)
        return url, json.dumps(value).encode(), "application/json"

    monkeypatch.setattr(productivity, "fetch_public", fetch)
    return runtime.productivity, clock, calls, state


async def test_default_forecast_includes_seven_days_conditions_units_and_current(weather_service):
    service, _, calls, _ = weather_service
    result = await service.weather("cloud")
    assert result["state"] == "ready" and result["forecast"]["complete"]
    assert result["forecast"]["days"] == 7
    assert result["daily"]["time"] == [f"2026-03-{day}" for day in range(28, 32)] + ["2026-04-01", "2026-04-02", "2026-04-03"]
    assert result["daily"]["weather_code"] == [61] * 7
    assert result["daily"]["precipitation_probability_max"] == [70] * 7
    assert result["current"]["temperature_2m"] == 99
    assert result["daily_units"]["temperature_2m_min"] == "°C"
    assert result["timezone"] == "Europe/Rome" and not result["stale"]
    query = parse_qs(urlsplit(calls[-1]).query)
    assert query["forecast_days"] == ["16"] and "hourly" not in query
    assert "weather_code" in query["daily"][0] and "precipitation_probability_max" in query["daily"][0]
    assert query["wind_speed_unit"] == ["kmh"]


async def test_requested_dates_and_longer_ranges_share_cache_without_truncating_it(weather_service):
    service, _, calls, _ = weather_service
    default = await service.weather("cloud")
    tomorrow = await service.weather("cloud", start_date="2026-03-29", days=2)
    assert tomorrow["daily"]["time"] == ["2026-03-29", "2026-03-30"]
    assert tomorrow["daily"]["temperature_2m_max"] == [21, 22]
    assert tomorrow["forecast"]["start_date"] == "2026-03-29"
    assert tomorrow["forecast"]["end_date"] == "2026-03-30"
    assert tomorrow["forecast"]["complete"]
    full = await service.weather("cloud", days=16)
    last = await service.weather("cloud", start_date="2026-04-12", days=1)
    assert len(full["daily"]["time"]) == 16 and last["daily"]["temperature_2m_max"] == [35]
    assert len(default["daily"]["time"]) == 7 and len(calls) == 2


@pytest.mark.parametrize("days", [0, -1, 17, 1000000, True, 1.5])
async def test_invalid_forecast_lengths_never_reach_the_network(weather_service, days):
    service, _, calls, _ = weather_service
    with pytest.raises(ValueError, match="between 1 and 16"):
        await service.weather("cloud", days=days)
    assert not calls


@pytest.mark.parametrize("start_date,days", [
    ("tomorrow", 1), ("https://example.invalid/?data=fixture", 1),
    ("2026-02-30", 1), ("20260328", 1), ("9999-12-31", 2),
    ("2026-03-27", 1), ("2026-04-13", 1), ("2026-04-12", 2),
])
async def test_invalid_or_out_of_horizon_dates_never_reach_the_network(weather_service, start_date, days):
    service, _, calls, _ = weather_service
    with pytest.raises(ValueError, match="ISO date|Forecasts are available"):
        await service.weather("cloud", start_date=start_date, days=days)
    assert not calls


async def test_stale_fallback_preserves_requested_future_dates_and_freshness(weather_service):
    service, _, _, state = weather_service
    await service.weather("cloud")
    for key, (_, value) in list(service.weather_cache.items()):
        service.weather_cache[key] = (time.monotonic() - 3600, value)
    state["offline"] = True
    result = await service.weather("cloud", start_date="2026-03-29", days=2)
    assert result["stale"] and result["daily"]["time"] == ["2026-03-29", "2026-03-30"]
    assert result["forecast"]["complete"]


async def test_local_midnight_refreshes_calendar_coverage_even_during_cache_ttl(weather_service):
    service, clock, calls, _ = weather_service
    old = await service.weather("cloud")
    clock[0] = datetime(2026, 3, 28, 23, 30, tzinfo=UTC)
    current = await service.weather("cloud")
    assert old["forecast"]["start_date"] == "2026-03-28"
    assert current["forecast"]["start_date"] == "2026-03-29"
    assert len(calls) == 4


async def test_time_zone_change_does_not_reuse_wrong_daily_boundaries(runtime, weather_service):
    service, _, calls, _ = weather_service
    await service.weather("cloud")
    runtime.config.update({"timezone": "America/New_York"})
    result = await service.weather("cloud")
    assert result["timezone"] == "America/New_York" and len(calls) == 4


async def test_provider_partial_coverage_is_explicit_instead_of_invented(weather_service):
    service, _, _, state = weather_service
    state["limit"] = 3
    result = await service.weather("cloud", days=7)
    assert result["forecast"]["days"] == 3 and result["forecast"]["requested_days"] == 7
    assert not result["forecast"]["complete"]
    assert result["forecast"]["end_date"] == "2026-03-30"


@pytest.mark.parametrize("problem", ["dates", "duplicate", "length", "empty"])
async def test_malformed_daily_data_does_not_poison_cache(weather_service, problem):
    service, _, _, state = weather_service

    def mutate(value):
        if problem == "dates":
            value["daily"]["time"][0] = "not-a-date"
        elif problem == "duplicate":
            value["daily"]["time"][1] = value["daily"]["time"][0]
        elif problem == "length":
            value["daily"]["temperature_2m_min"].pop()
        else:
            value["daily"]["time"] = []

    state["mutate"] = mutate
    with pytest.raises(ValueError, match="weather provider"):
        await service.weather("cloud")
    assert not service.weather_cache


async def test_strict_offline_mode_still_prohibits_forecasts(weather_service):
    service, _, calls, _ = weather_service
    with pytest.raises(PermissionError, match="strict local"):
        await service.weather("local_strict", days=7)
    assert not calls


@pytest.mark.parametrize("channel", ["text", "live"])
async def test_agent_forwards_future_date_range_after_history_without_approval(runtime, weather_service, monkeypatch, channel):
    monkeypatch.setattr(runtime.tasks, "model", model_factory())
    prior = await runtime.tasks.create("Tell me the time", channel=channel)
    await runtime.tasks.running[prior["id"]]
    monkeypatch.setattr(runtime.tasks, "model", model_factory("weather", {
        "location": "Fixture City", "start_date": "2026-03-29", "days": 2,
    }))
    task = await runtime.tasks.create("Che tempo farà il 29 e 30 marzo a Fixture City?", conversation_id=prior["conversation_id"], channel=channel)
    await runtime.tasks.running[task["id"]]
    row = await runtime.db.fetchone("SELECT * FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "succeeded", row["error"]
    assert "2026-03-29" in row["result"] and "2026-03-30" in row["result"]
    assert not await runtime.db.fetchall("SELECT * FROM approvals")
