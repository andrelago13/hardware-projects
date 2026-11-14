import hmac
import math
import os
from typing import Any

import functions_framework
import psycopg


def _get_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _parse_number(payload: dict[str, Any], key: str) -> float:
    if key not in payload:
        raise ValueError(f"Missing field: {key}")
    val = payload[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError(f"Field '{key}' must be a number")
    num = float(val)
    if not math.isfinite(num):
        raise ValueError(f"Field '{key}' must be finite")
    return num


def _parse_int(payload: dict[str, Any], key: str, default: int | None = None) -> int:
    if key not in payload:
        if default is not None:
            return default
        raise ValueError(f"Missing field: {key}")
    val = payload[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ValueError(f"Field '{key}' must be an integer")
    return val


def validate_reading(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")

    device_id = payload.get("deviceId")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("Field 'deviceId' must be a non-empty string")

    temperature_c = _parse_number(payload, "temperatureC")
    humidity_pct = _parse_number(payload, "humidityPct")
    if not (0.0 <= humidity_pct <= 100.0):
        raise ValueError("Field 'humidityPct' must be between 0 and 100")

    soil_moisture_pct = _parse_int(payload, "soilMoisturePct")
    if not (0 <= soil_moisture_pct <= 100):
        raise ValueError("Field 'soilMoisturePct' must be between 0 and 100")

    uptime_seconds = _parse_int(payload, "uptimeSeconds", default=0)
    boot_count = _parse_int(payload, "bootCount", default=0)
    if uptime_seconds < 0:
        raise ValueError("Field 'uptimeSeconds' must be >= 0")
    if boot_count < 0:
        raise ValueError("Field 'bootCount' must be >= 0")

    return {
        "device_id": device_id.strip(),
        "temperature_c": temperature_c,
        "humidity_pct": humidity_pct,
        "soil_moisture_pct": soil_moisture_pct,
        "uptime_seconds": uptime_seconds,
        "boot_count": boot_count,
    }


def insert_reading(reading: dict[str, Any]) -> None:
    database_url = os.environ.get("DATABASE_URL_POOLED") or _get_env("DATABASE_URL")
    with psycopg.connect(
        database_url,
        prepare_threshold=None,
        connect_timeout=10,
    ) as conn:
        conn.execute(
            """
            INSERT INTO readings (
                device_id,
                temperature_c,
                humidity_pct,
                soil_moisture_pct,
                uptime_seconds,
                boot_count
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                reading["device_id"],
                reading["temperature_c"],
                reading["humidity_pct"],
                reading["soil_moisture_pct"],
                reading["uptime_seconds"],
                reading["boot_count"],
            ),
        )


@functions_framework.http
def ingest_reading(request):
    if request.method == "GET":
        return ({"ok": True, "service": "plant-monitor-ingest"}, 200)

    if request.method != "POST":
        return ({"error": "Method not allowed"}, 405)

    expected_key = _get_env("API_KEY")
    provided_key = request.headers.get("X-API-Key", "")
    if not provided_key or not hmac.compare_digest(provided_key, expected_key):
        return ({"error": "Unauthorized"}, 401)

    payload = request.get_json(silent=True)
    try:
        reading = validate_reading(payload)
    except ValueError as exc:
        return ({"error": str(exc)}, 400)

    insert_reading(reading)
    return ({"ok": True}, 201)
