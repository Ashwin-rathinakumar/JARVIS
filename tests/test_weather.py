import unittest
from unittest.mock import MagicMock, patch

from app.tools.weather import get_weather


def response(payload):
    item = MagicMock()
    item.json.return_value = payload
    item.raise_for_status.return_value = None
    return item


class TestWeatherTool(unittest.TestCase):
    @patch("app.tools.weather.requests.get")
    def test_current_weather_uses_live_provider_data(self, get):
        get.side_effect = [
            response({"results": [{"name": "Chennai", "admin1": "Tamil Nadu", "country": "India",
                                   "latitude": 13.08, "longitude": 80.27}]}),
            response({
                "current": {"weather_code": 1, "temperature_2m": 31.2, "apparent_temperature": 35.0,
                            "precipitation": 0.0, "rain": 0.0, "wind_speed_10m": 12.1},
                "current_units": {"temperature_2m": "°C", "apparent_temperature": "°C",
                                  "precipitation": " mm", "wind_speed_10m": " km/h"},
            }),
        ]
        result = get_weather("Chennai")
        self.assertTrue(result["success"])
        self.assertIn("Chennai, Tamil Nadu, India", result["message"])
        self.assertIn("31.2°C", result["message"])
        self.assertEqual(get.call_count, 2)

    @patch("app.tools.weather.requests.get")
    def test_tomorrow_forecast_uses_daily_data(self, get):
        get.side_effect = [
            response({"results": [{"name": "Bengaluru", "country": "India",
                                   "latitude": 12.97, "longitude": 77.59}]}),
            response({
                "daily": {"weather_code": [2, 61], "temperature_2m_max": [28, 25],
                          "temperature_2m_min": [20, 19], "precipitation_probability_max": [20, 75]},
                "daily_units": {"temperature_2m_max": "°C", "temperature_2m_min": "°C",
                                "precipitation_probability_max": "%"},
            }),
        ]
        result = get_weather("Bengaluru", "tomorrow")
        self.assertTrue(result["success"])
        self.assertIn("tomorrow", result["message"])
        self.assertIn("75%", result["message"])

    @patch("app.tools.weather.requests.get")
    def test_location_not_found_is_truthful(self, get):
        get.return_value = response({"results": []})
        result = get_weather("Definitely Not A Place")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "WEATHER_LOCATION_NOT_FOUND")

    @patch("app.tools.weather.requests.get", side_effect=Exception("provider unavailable"))
    def test_unexpected_provider_failure_does_not_escape_or_fabricate(self, _get):
        result = get_weather("Chennai")
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "I couldn't retrieve live weather data right now.")

    def test_missing_location_is_rejected_without_network(self):
        result = get_weather("")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "WEATHER_LOCATION_REQUIRED")


if __name__ == "__main__":
    unittest.main()
