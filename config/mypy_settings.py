from __future__ import annotations

import os

# ---- Safe defaults so importing config.settings.
# won't explode during mypy ----
os.environ.setdefault("DJANGO_SECRET_KEY", "mypy-only-not-for-prod")
os.environ.setdefault("DATABASE_URL", "sqlite:///mypy.sqlite3")
os.environ.setdefault("DJANGO_API_KEY_PEPPER", "mypy-only-pepper")

# If your real settings require other env vars (e.g. REDIS_URL, SENTRY_DSN),
# add more os.environ.setdefault(...) lines here.

from .settings import *  # noqa: F401,F403

# Optional hard overrides for mypy environment:
DEBUG = False
USE_TZ = True
