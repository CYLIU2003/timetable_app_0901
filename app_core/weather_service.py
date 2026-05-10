from __future__ import annotations

import logging
from typing import Any

import requests

from .cache import TtlCache
from .config import WEATHER_CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)
_weather_cache = TtlCache()

W_URL = "https://weather.tsukumijima.net/api/forecast/city/130010"


def _load_weather() -> dict[str, Any]:
    response = requests.get(W_URL, timeout=6)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("weather payload must be a dict")
    return payload


def get_weather() -> dict[str, Any]:
    try:
        return _weather_cache.get_or_set("weather", WEATHER_CACHE_TTL_SECONDS, _load_weather)
    except Exception as exc:
        logger.warning("Weather error: %s", exc)
        return {}