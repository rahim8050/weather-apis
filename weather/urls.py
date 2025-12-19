from __future__ import annotations

from django.urls import path

from .views import WeatherCurrentView, WeatherDailyView, WeatherWeeklyView

urlpatterns = [
    path(
        "weather/current/",
        WeatherCurrentView.as_view(),
        name="weather-current",
    ),
    path(
        "weather/daily/",
        WeatherDailyView.as_view(),
        name="weather-daily",
    ),
    path(
        "weather/weekly/",
        WeatherWeeklyView.as_view(),
        name="weather-weekly",
    ),
]
