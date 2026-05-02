from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from pathology.models import CrawlJob
from pathology.services.jobs import CrawlJobRunner
from pathology.services.pipeline import CrawlStopped


class Command(BaseCommand):
    help = "Run one crawl job in the background."

    def add_arguments(self, parser):
        parser.add_argument("--job-id", type=int, required=True)

    def handle(self, *args, **options):
        try:
            job = CrawlJob.objects.get(pk=options["job_id"])
        except CrawlJob.DoesNotExist as exc:
            raise CommandError("Crawl job not found.") from exc

        runner = CrawlJobRunner(job)
        try:
            summary = runner.run()
        except CrawlStopped:
            self.stdout.write(self.style.WARNING("Crawl job stopped by user request."))
            return

        self.stdout.write(self.style.SUCCESS("Crawl job completed."))
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")
