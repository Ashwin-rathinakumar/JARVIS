"""Live weather retrieval using Open-Meteo's keyless public APIs."""
from typing import Any, Dict
import requests

from app.config.settings import WEATHER_FORECAST_URL, WEATHER_GEOCODING_URL, WEATHER_TIMEOUT
from app.utils.logger import logger


WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 56: "light freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "light freezing rain",
    67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "light rain showers", 81: "rain showers",
    82: "heavy rain showers", 85: "light snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with light hail", 99: "thunderstorm with hail",
}


def _failure(message: str, code: str = "WEATHER_UNAVAILABLE") -> Dict[str, Any]:
    return {"success": False, "message": message, "error_code": code, "error": message}


def get_weather(location: str, when: str = "current") -> Dict[str, Any]:
    """Fetch current/today/tomorrow weather without inventing unavailable values."""
    location = (location or "").strip()
    if not location:
        return _failure("Please tell me which location you want weather for.", "WEATHER_LOCATION_REQUIRED")

    try:
        geocode = requests.get(
            WEATHER_GEOCODING_URL,
            params={"name": location, "count": 1, "language": "en", "format": "json"},
            timeout=WEATHER_TIMEOUT,
        )
        geocode.raise_for_status()
        candidates = geocode.json().get("results") or []
        if not candidates:
            return _failure(f"I couldn't find a weather location matching '{location}'.", "WEATHER_LOCATION_NOT_FOUND")

        place = candidates[0]
        forecast = requests.get(
            WEATHER_FORECAST_URL,
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "timezone": "auto",
                "current": "temperature_2m,apparent_temperature,precipitation,rain,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "forecast_days": 2,
            },
            timeout=WEATHER_TIMEOUT,
        )
        forecast.raise_for_status()
        payload = forecast.json()
        display_name = ", ".join(filter(None, [place.get("name"), place.get("admin1"), place.get("country")]))

        if when in {"today", "tomorrow"}:
            index = 1 if when == "tomorrow" else 0
            daily = payload.get("daily") or {}
            try:
                code = daily["weather_code"][index]
                low = daily["temperature_2m_min"][index]
                high = daily["temperature_2m_max"][index]
                rain_chance = daily["precipitation_probability_max"][index]
                units = payload.get("daily_units") or {}
            except (KeyError, IndexError, TypeError):
                return _failure("I couldn't retrieve complete live weather data right now.")
            message = (
                f"Weather for {display_name} {when}: {WEATHER_CODES.get(code, 'weather code ' + str(code))}, "
                f"{low}{units.get('temperature_2m_min', '°C')} to {high}{units.get('temperature_2m_max', '°C')}, "
                f"with a maximum precipitation chance of {rain_chance}{units.get('precipitation_probability_max', '%')}."
            )
            data = {"location": display_name, "when": when, "weather_code": code,
                    "temperature_min": low, "temperature_max": high, "precipitation_probability_max": rain_chance}
        else:
            current = payload.get("current") or {}
            try:
                code = current["weather_code"]
                temperature = current["temperature_2m"]
                apparent = current["apparent_temperature"]
                precipitation = current["precipitation"]
                wind = current["wind_speed_10m"]
                units = payload.get("current_units") or {}
            except KeyError:
                return _failure("I couldn't retrieve complete live weather data right now.")
            message = (
                f"Current weather in {display_name}: {WEATHER_CODES.get(code, 'weather code ' + str(code))}, "
                f"{temperature}{units.get('temperature_2m', '°C')}, feels like "
                f"{apparent}{units.get('apparent_temperature', '°C')}. Precipitation is "
                f"{precipitation}{units.get('precipitation', ' mm')} and wind is "
                f"{wind}{units.get('wind_speed_10m', ' km/h')}."
            )
            data = {"location": display_name, "when": "current", "weather_code": code,
                    "temperature": temperature, "apparent_temperature": apparent,
                    "precipitation": precipitation, "wind_speed": wind}

        return {"success": True, "message": message, "data": data}
    except Exception as error:
        logger.warning("Live weather retrieval failed for %r: %s", location, error)
        return _failure("I couldn't retrieve live weather data right now.")
