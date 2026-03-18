"""
Phase 5 — Weather Data Feed.

Free weather data for Kalshi weather markets (temperature, hurricane,
precipitation, etc.):
  • OpenWeatherMap (free tier: 1000 calls/day)
  • NOAA Climate Data (completely free, no key)
  • National Hurricane Center RSS (free)

Direct signal for weather-category Kalshi markets.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.intelligence.base import DataSource, DataSourceType, SourceHealth, SourceSignal
from app.logging_config import get_logger

log = get_logger("intelligence.weather")

# Major US cities Kalshi tracks weather for
WEATHER_CITIES = {
    "new_york": {"lat": 40.7128, "lon": -74.0060, "name": "New York"},
    "los_angeles": {"lat": 34.0522, "lon": -118.2437, "name": "Los Angeles"},
    "chicago": {"lat": 41.8781, "lon": -87.6298, "name": "Chicago"},
    "houston": {"lat": 29.7604, "lon": -95.3698, "name": "Houston"},
    "phoenix": {"lat": 33.4484, "lon": -112.0740, "name": "Phoenix"},
    "miami": {"lat": 25.7617, "lon": -80.1918, "name": "Miami"},
    "dallas": {"lat": 32.7767, "lon": -96.7970, "name": "Dallas"},
    "denver": {"lat": 39.7392, "lon": -104.9903, "name": "Denver"},
    "atlanta": {"lat": 33.7490, "lon": -84.3880, "name": "Atlanta"},
    "washington_dc": {"lat": 38.9072, "lon": -77.0369, "name": "Washington DC"},
}

# NOAA endpoints
NOAA_ALERTS_URL = "https://api.weather.gov/alerts/active"
NHC_RSS_URL = "https://www.nhc.noaa.gov/index-at.xml"


class WeatherDataFeed(DataSource):
    """
    Multi-source weather data for Kalshi weather market predictions.
    """

    def __init__(
        self,
        openweathermap_key: str = "",
        poll_interval: float = 300.0,
        enabled: bool = True,
    ) -> None:
        self._owm_key = openweathermap_key
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        self._weather_cache: dict[str, dict[str, Any]] = {}
        self._alerts_cache: list[dict] = []
        self._stats = {
            "owm_fetches": 0, "owm_errors": 0,
            "noaa_fetches": 0, "noaa_errors": 0,
            "total_signals": 0,
        }

    @property
    def name(self) -> str:
        return "weather_feed"

    @property
    def source_type(self) -> DataSourceType:
        return DataSourceType.WEATHER

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            headers={"User-Agent": "(JA-Hedge, contact@frankensteintrading.com)"},
            follow_redirects=True,
        )
        log.info("weather_feed_started", has_owm_key=bool(self._owm_key))

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        # Fetch OpenWeatherMap current conditions
        if self._owm_key:
            for city_id, city_info in WEATHER_CITIES.items():
                try:
                    weather = await self._fetch_owm(city_info["lat"], city_info["lon"])
                    if weather:
                        self._weather_cache[city_id] = weather
                        sig = self._weather_to_signal(city_id, city_info, weather)
                        if sig:
                            signals.append(sig)
                except Exception as e:
                    self._stats["owm_errors"] += 1
                    log.debug("owm_error", city=city_id, error=str(e))

        # Fetch NOAA alerts (free, no key)
        try:
            alerts = await self._fetch_noaa_alerts()
            for alert_sig in alerts:
                signals.append(alert_sig)
        except Exception as e:
            self._stats["noaa_errors"] += 1
            log.debug("noaa_alerts_error", error=str(e))

        # Fetch NOAA point forecasts (free, no key) for key cities
        for city_id, city_info in list(WEATHER_CITIES.items())[:5]:
            try:
                forecast_sig = await self._fetch_noaa_forecast(city_id, city_info)
                if forecast_sig:
                    signals.append(forecast_sig)
            except Exception as e:
                log.debug("noaa_forecast_error", city=city_id, error=str(e))

        self._stats["total_signals"] += len(signals)
        return signals

    async def _fetch_owm(self, lat: float, lon: float) -> dict | None:
        """Fetch current weather from OpenWeatherMap."""
        if not self._client or not self._owm_key:
            return None

        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "lat": str(lat),
            "lon": str(lon),
            "appid": self._owm_key,
            "units": "imperial",
        }
        resp = await self._client.get(url, params=params)
        self._stats["owm_fetches"] += 1

        if resp.status_code != 200:
            self._stats["owm_errors"] += 1
            return None

        return resp.json()

    def _weather_to_signal(self, city_id: str, city_info: dict, weather: dict) -> SourceSignal | None:
        """Convert OWM weather data to a SourceSignal."""
        main = weather.get("main", {})
        temp_f = main.get("temp", 0)
        humidity = main.get("humidity", 0)
        wind = weather.get("wind", {}).get("speed", 0)
        rain_1h = weather.get("rain", {}).get("1h", 0)
        snow_1h = weather.get("snow", {}).get("1h", 0)
        condition = weather.get("weather", [{}])[0].get("main", "")

        # Signal value: how "extreme" is the weather?
        extreme_score = 0.0
        if temp_f > 100:
            extreme_score = (temp_f - 100) / 20  # > 100°F
        elif temp_f < 32:
            extreme_score = (32 - temp_f) / 30  # < 32°F
        if wind > 30:
            extreme_score += (wind - 30) / 20
        if rain_1h > 0.5:
            extreme_score += rain_1h / 2
        if snow_1h > 0.5:
            extreme_score += snow_1h

        extreme_score = min(1.0, extreme_score)

        return SourceSignal(
            source_name=self.name,
            source_type=self.source_type,
            ticker=f"weather:{city_id}",
            signal_value=extreme_score,
            confidence=0.85,  # Weather data is highly reliable
            category="weather",
            headline=f"{city_info['name']}: {temp_f:.0f}°F, {condition}",
            features={
                "temp_f": round(temp_f, 1),
                "humidity": humidity,
                "wind_mph": round(wind, 1),
                "rain_1h_in": round(rain_1h, 2),
                "snow_1h_in": round(snow_1h, 2),
                "extreme_score": round(extreme_score, 4),
            },
            raw_data=weather,
        )

    async def _fetch_noaa_alerts(self) -> list[SourceSignal]:
        """Fetch active weather alerts from NOAA (free, no key)."""
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        try:
            resp = await self._client.get(NOAA_ALERTS_URL, params={
                "status": "actual",
                "message_type": "alert",
                "limit": "50",
            })
            self._stats["noaa_fetches"] += 1

            if resp.status_code != 200:
                self._stats["noaa_errors"] += 1
                return []

            data = resp.json()
            features = data.get("features", [])
            self._alerts_cache = []

            for feature in features[:20]:
                props = feature.get("properties", {})
                event = props.get("event", "")
                severity = props.get("severity", "")
                headline = props.get("headline", "")
                area = props.get("areaDesc", "")

                severity_score = {
                    "Extreme": 1.0, "Severe": 0.8, "Moderate": 0.5, "Minor": 0.2,
                }.get(severity, 0.1)

                self._alerts_cache.append({
                    "event": event,
                    "severity": severity,
                    "headline": headline,
                    "area": area,
                })

                signals.append(SourceSignal(
                    source_name=self.name,
                    source_type=self.source_type,
                    ticker=f"weather:alert:{event.lower().replace(' ', '_')}",
                    signal_value=severity_score,
                    confidence=0.9,
                    category="weather",
                    headline=headline[:200],
                    features={
                        "alert_severity": severity_score,
                        "alert_type": event,
                    },
                    raw_data={"event": event, "severity": severity, "area": area},
                ))

        except Exception as e:
            self._stats["noaa_errors"] += 1
            log.debug("noaa_error", error=str(e))

        return signals

    async def _fetch_noaa_forecast(self, city_id: str, city_info: dict) -> SourceSignal | None:
        """Fetch NWS point forecast (free, no key)."""
        if not self._client:
            return None

        try:
            # Step 1: Get forecast office from coordinates
            point_url = f"https://api.weather.gov/points/{city_info['lat']},{city_info['lon']}"
            resp = await self._client.get(point_url)
            if resp.status_code != 200:
                return None

            point_data = resp.json()
            forecast_url = point_data.get("properties", {}).get("forecast")
            if not forecast_url:
                return None

            # Step 2: Get the forecast
            resp = await self._client.get(forecast_url)
            self._stats["noaa_fetches"] += 1
            if resp.status_code != 200:
                return None

            forecast_data = resp.json()
            periods = forecast_data.get("properties", {}).get("periods", [])
            if not periods:
                return None

            # Use first period (today/tonight)
            p = periods[0]
            temp = p.get("temperature", 0)
            wind_speed = p.get("windSpeed", "")
            precip_pct = p.get("probabilityOfPrecipitation", {}).get("value") or 0
            short_forecast = p.get("shortForecast", "")

            return SourceSignal(
                source_name=self.name,
                source_type=self.source_type,
                ticker=f"weather:forecast:{city_id}",
                signal_value=precip_pct / 100.0 if precip_pct else 0.0,
                confidence=0.80,
                category="weather",
                headline=f"{city_info['name']} forecast: {short_forecast}, {temp}°F",
                features={
                    "forecast_temp_f": float(temp),
                    "forecast_precip_pct": float(precip_pct or 0),
                    "forecast_period": p.get("name", ""),
                },
            )

        except Exception as e:
            log.debug("noaa_forecast_error", city=city_id, error=str(e))
            return None

    def health(self) -> SourceHealth:
        return SourceHealth(
            name=self.name,
            source_type=self.source_type,
            enabled=self._enabled,
            healthy=True,
            total_fetches=self._stats["owm_fetches"] + self._stats["noaa_fetches"],
            total_errors=self._stats["owm_errors"] + self._stats["noaa_errors"],
            total_signals=self._stats["total_signals"],
        )
