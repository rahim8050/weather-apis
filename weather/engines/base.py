from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date

from .types import CurrentWeather, DailyForecast, Location, ProviderName


class WeatherProvider(ABC):
    """Abstract base for weather providers."""

    name: ProviderName

    @abstractmethod
    async def current(self, loc: Location) -> CurrentWeather:
        """Return current conditions for a location."""

    @abstractmethod
    async def daily(
        self, loc: Location, start: date, end: date
    ) -> Sequence[DailyForecast]:
        """Return daily observations for the inclusive date range."""
