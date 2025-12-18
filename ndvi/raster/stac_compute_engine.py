from __future__ import annotations

from .base import NdviRasterEngine, RasterRequest


class StacComputeRasterEngine(NdviRasterEngine):
    """Placeholder for STAC-based raster rendering."""

    def render_png(
        self, request: RasterRequest
    ) -> bytes:  # pragma: no cover - stub
        raise NotImplementedError("STAC raster engine not implemented yet")
