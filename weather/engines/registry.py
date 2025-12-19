from __future__ import annotations

from typing import cast

from django.conf import settings

from .base import WeatherProvider
from .nasa_power import NasaPowerProvider
from .open_meteo import OpenMeteoProvider
from .types import ProviderName


def build_registry() -> dict[ProviderName, WeatherProvider]:
    """Instantiate supported providers."""

    providers: dict[ProviderName, WeatherProvider] = {
        "open_meteo": OpenMeteoProvider(),
        "nasa_power": NasaPowerProvider(),
    }
    return providers


def default_provider_name() -> ProviderName:
    configured = getattr(settings, "WEATHER_PROVIDER_DEFAULT", "open_meteo")
    return cast(ProviderName, configured.lower())


def validate_provider(
    provider: str | None, registry: dict[ProviderName, WeatherProvider]
) -> ProviderName:
    name = (provider or default_provider_name()).lower()
    if name not in registry:
        raise ValueError(f"Unsupported weather provider: {name}")
    return cast(ProviderName, name)
