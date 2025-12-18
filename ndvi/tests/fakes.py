from __future__ import annotations

import base64

from ndvi.raster.base import NdviRasterEngine, RasterRequest

_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+pL90AAAAASUVORK5CYII="
)


class FakeRasterEngine(NdviRasterEngine):
    """Simple raster engine that returns a 1x1 PNG."""

    def render_png(self, request: RasterRequest) -> bytes:  # noqa: D401
        return _PNG_BYTES
