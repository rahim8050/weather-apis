from __future__ import annotations

from functools import lru_cache

from django.conf import settings
from django.utils.module_loading import import_string

from .base import NdviRasterEngine


@lru_cache(maxsize=1)
def get_engine() -> NdviRasterEngine:
    """Return the configured raster engine instance."""

    engine_path = getattr(
        settings,
        "NDVI_RASTER_ENGINE_PATH",
        "ndvi.raster.sentinelhub_engine.SentinelHubRasterEngine",
    )
    engine_cls: type[NdviRasterEngine] = import_string(engine_path)
    return engine_cls()  # type: ignore[call-arg]
