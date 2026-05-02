from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from pathology.models import CrawlJob

from .pipeline import CrawlStopped, ProtocolIngestionPipeline

logger = logging.getLogger("pathology.jobs")


class CrawlJobService:
    def start_job(self, job: CrawlJob) -> CrawlJob:
        if job.status == CrawlJob.Status.RUNNING:
            return job

        job.stop_requested = False
        job.error_message = ""
        job.status = CrawlJob.Status.PENDING
        job.save(update_fields=["stop_requested", "error_message", "status"])

        log_path = settings.LOG_DIR / f"crawl_job_{job.pk}.log"
        with log_path.open("ab") as log_handle:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "manage.py",
                    "run_crawl_job",
                    "--job-id",
                    str(job.pk),
                ],
                cwd=settings.BASE_DIR,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )

        job.process_id = process.pid
        job.save(update_fields=["process_id"])
        logger.info("Started crawl job %s with pid %s", job.pk, process.pid)
        return job

    def request_stop(self, job: CrawlJob) -> CrawlJob:
        updates = ["stop_requested"]
        job.stop_requested = True
        if job.status == CrawlJob.Status.RUNNING:
            job.status = CrawlJob.Status.STOP_REQUESTED
            updates.append("status")
        job.save(update_fields=updates)
        logger.info("Stop requested for crawl job %s", job.pk)
        return job


class CrawlJobRunner:
    def __init__(self, job: CrawlJob):
        self.job = job
        self.pipeline = ProtocolIngestionPipeline()

    def run(self) -> dict[str, int]:
        self._mark_running()
        destination = Path(self.job.destination_dir) if self.job.destination_dir else None

        try:
            summary = self.pipeline.run(
                limit=self.job.limit,
                destination_root=destination,
                should_stop=self.should_stop,
                progress_callback=self._update_progress,
            )
        except CrawlStopped:
            self.job.refresh_from_db()
            self.job.status = CrawlJob.Status.STOPPED
            self.job.finished_at = timezone.now()
            self.job.process_id = None
            self.job.save(update_fields=["status", "finished_at", "process_id"])
            logger.info("Crawl job %s stopped by user request", self.job.pk)
            raise
        except Exception as exc:
            self.job.refresh_from_db()
            self.job.status = CrawlJob.Status.FAILED
            self.job.error_message = str(exc)
            self.job.finished_at = timezone.now()
            self.job.process_id = None
            self.job.save(
                update_fields=["status", "error_message", "finished_at", "process_id"]
            )
            logger.exception("Crawl job %s failed", self.job.pk)
            raise

        self.job.refresh_from_db()
        self.job.status = CrawlJob.Status.COMPLETED
        self.job.finished_at = timezone.now()
        self.job.process_id = None
        self._apply_summary(summary)
        self.job.save(
            update_fields=[
                "status",
                "finished_at",
                "process_id",
                "total_links",
                "files_downloaded",
                "records_created",
                "records_updated",
                "records_skipped",
            ]
        )
        logger.info("Crawl job %s completed", self.job.pk)
        return summary

    def should_stop(self) -> bool:
        self.job.refresh_from_db(fields=["stop_requested"])
        return self.job.stop_requested

    def _mark_running(self) -> None:
        self.job.refresh_from_db()
        self.job.status = CrawlJob.Status.RUNNING
        self.job.started_at = timezone.now()
        self.job.finished_at = None
        self.job.error_message = ""
        if not self.job.process_id:
            self.job.process_id = os.getpid()
        self.job.save(
            update_fields=["status", "started_at", "finished_at", "error_message", "process_id"]
        )

    def _update_progress(self, summary: dict[str, int]) -> None:
        self.job.refresh_from_db(fields=["status", "stop_requested"])
        if self.job.stop_requested and self.job.status == CrawlJob.Status.RUNNING:
            self.job.status = CrawlJob.Status.STOP_REQUESTED
        self._apply_summary(summary)
        self.job.save(
            update_fields=[
                "status",
                "total_links",
                "files_downloaded",
                "records_created",
                "records_updated",
                "records_skipped",
            ]
        )

    def _apply_summary(self, summary: dict[str, int]) -> None:
        self.job.total_links = summary.get("links", 0)
        self.job.files_downloaded = summary.get("files", 0)
        self.job.records_created = summary.get("created", 0)
        self.job.records_updated = summary.get("updated", 0)
        self.job.records_skipped = summary.get("skipped", 0)
