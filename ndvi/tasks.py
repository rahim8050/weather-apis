from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from farms.models import Farm

from .metrics import ndvi_jobs_total
from .models import NdviJob
from .services import (
    DEFAULT_ENGINE,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_CLOUD,
    DEFAULT_STEP_DAYS,
    LOCK_TIMEOUT_SECONDS,
    acquire_lock,
    enforce_quota,
    enqueue_job,
    get_engine,
    normalize_bbox,
    normalize_latest_params,
    normalize_timeseries_params,
    upsert_observations,
)

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_ndvi_job(self: Any, job_id: int) -> str:
    job = NdviJob.objects.select_related("farm", "owner").get(id=job_id)
    if not acquire_lock(job.request_hash, timeout=LOCK_TIMEOUT_SECONDS):
        logger.info("ndvi.lock.skipped job_id=%s", job.id)
        return "locked"

    try:
        bbox = normalize_bbox(job.farm)
        enforce_quota(job.farm, bbox)

        with transaction.atomic():
            job.mark_running(
                locked_until=timezone.now()
                + timedelta(seconds=LOCK_TIMEOUT_SECONDS)
            )

        engine = get_engine(job.engine)
        if job.job_type == NdviJob.JobType.REFRESH_LATEST:
            latest_params = normalize_latest_params(
                lookback_days=job.lookback_days or DEFAULT_LOOKBACK_DAYS,
                max_cloud=job.max_cloud or DEFAULT_MAX_CLOUD,
            )
            point = engine.get_latest(
                bbox=bbox,
                lookback_days=latest_params.lookback_days,
                max_cloud=latest_params.max_cloud,
            )
            if point:
                upsert_observations(
                    farm=job.farm, engine=job.engine, points=[point]
                )
        else:
            timeseries_params = normalize_timeseries_params(
                start=job.start
                or date.today() - timedelta(days=DEFAULT_STEP_DAYS),
                end=job.end or date.today(),
                step_days=job.step_days or DEFAULT_STEP_DAYS,
                max_cloud=job.max_cloud or DEFAULT_MAX_CLOUD,
            )
            points = engine.get_timeseries(
                bbox=bbox,
                start=timeseries_params.start,
                end=timeseries_params.end,
                step_days=timeseries_params.step_days,
                max_cloud=timeseries_params.max_cloud,
            )
            if points:
                upsert_observations(
                    farm=job.farm, engine=job.engine, points=points
                )
        job.mark_finished(NdviJob.JobStatus.SUCCESS)
        ndvi_jobs_total.labels(
            status=NdviJob.JobStatus.SUCCESS,
            type=job.job_type,
            engine=job.engine,
        ).inc()
        return "ok"
    except ValidationError as exc:
        logger.warning("ndvi.job.invalid job_id=%s err=%s", job.id, exc)
        job.mark_finished(NdviJob.JobStatus.FAILED, error=str(exc))
        ndvi_jobs_total.labels(
            status=NdviJob.JobStatus.FAILED,
            type=job.job_type,
            engine=job.engine,
        ).inc()
        return "invalid"
    except Exception as exc:  # noqa: BLE001
        logger.exception("ndvi.job.failed job_id=%s err=%s", job.id, exc)
        job.mark_finished(NdviJob.JobStatus.FAILED, error=str(exc))
        ndvi_jobs_total.labels(
            status=NdviJob.JobStatus.FAILED,
            type=job.job_type,
            engine=job.engine,
        ).inc()
        raise self.retry(exc=exc) from exc


@shared_task
def enqueue_daily_refresh() -> int:
    count = 0
    for farm in Farm.objects.filter(is_active=True):
        if (
            farm.bbox_south is None
            or farm.bbox_west is None
            or farm.bbox_north is None
            or farm.bbox_east is None
        ):
            continue
        job = enqueue_job(
            owner_id=farm.owner_id,
            farm=farm,
            engine=DEFAULT_ENGINE,
            job_type=NdviJob.JobType.REFRESH_LATEST,
            params={
                "lookback_days": DEFAULT_LOOKBACK_DAYS,
                "max_cloud": DEFAULT_MAX_CLOUD,
            },
        )
        run_ndvi_job.delay(job.id)
        count += 1
    return count


@shared_task
def enqueue_weekly_gap_fill() -> int:
    count = 0
    end = date.today()
    start = end - timedelta(days=120)
    for farm in Farm.objects.filter(is_active=True):
        if (
            farm.bbox_south is None
            or farm.bbox_west is None
            or farm.bbox_north is None
            or farm.bbox_east is None
        ):
            continue
        job = enqueue_job(
            owner_id=farm.owner_id,
            farm=farm,
            engine=DEFAULT_ENGINE,
            job_type=NdviJob.JobType.GAP_FILL,
            params={
                "start": start,
                "end": end,
                "step_days": 7,
                "max_cloud": DEFAULT_MAX_CLOUD,
            },
        )
        run_ndvi_job.delay(job.id)
        count += 1
    return count
