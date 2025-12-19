from __future__ import annotations

from prometheus_client import Counter, Histogram

weather_provider_requests_total = Counter(
    "weather_provider_requests_total",
    "Total weather provider requests",
    labelnames=["provider", "endpoint"],
)

weather_provider_errors_total = Counter(
    "weather_provider_errors_total",
    "Total weather provider request errors",
    labelnames=["provider", "endpoint", "error_type"],
)

weather_provider_latency_seconds = Histogram(
    "weather_provider_latency_seconds",
    "Latency of weather provider requests",
    labelnames=["provider", "endpoint"],
    buckets=(0.1, 0.3, 0.5, 1, 2, 5, 10, 20, 30),
)

weather_cache_hits_total = Counter(
    "weather_cache_hits_total",
    "Cache hits for weather services",
    labelnames=["provider", "endpoint"],
)

weather_cache_misses_total = Counter(
    "weather_cache_misses_total",
    "Cache misses for weather services",
    labelnames=["provider", "endpoint"],
)
