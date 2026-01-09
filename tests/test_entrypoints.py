from __future__ import annotations

import importlib
import sys

import pytest

import manage


def test_manage_main_invokes_execute_from_command_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {}

    def _fake_execute(argv: list[str]) -> None:
        called["argv"] = argv

    monkeypatch.setattr(
        "django.core.management.execute_from_command_line",
        _fake_execute,
    )
    monkeypatch.setattr(sys, "argv", ["manage.py", "check"])

    manage.main()

    assert called["argv"] == ["manage.py", "check"]


def test_asgi_application_importable() -> None:
    module = importlib.import_module("config.asgi")
    module = importlib.reload(module)
    assert module.application is not None


def test_wsgi_application_importable() -> None:
    module = importlib.import_module("config.wsgi")
    module = importlib.reload(module)
    assert module.application is not None


def test_mypy_settings_importable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DJANGO_SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///mypy.sqlite3")
    monkeypatch.setenv("DJANGO_API_KEY_PEPPER", "test-pepper")

    module = importlib.import_module("config.mypy_settings")
    module = importlib.reload(module)

    assert module.DEBUG is False
    assert module.USE_TZ is True
