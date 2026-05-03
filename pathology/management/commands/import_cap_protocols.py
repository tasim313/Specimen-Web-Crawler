from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand

from pathology.models import CrawlJob
from pathology.services.pipeline import ProtocolIngestionPipeline


class Command(BaseCommand):
    help = "Crawl CAP protocol templates, extract pathology data, and store it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit the number of documents processed for smoke testing.",
        )
        parser.add_argument(
            "--destination",
            type=str,
            default=None,
            help="Optional destination directory for downloaded CAP files.",
        )
        parser.add_argument(
            "--source",
            type=str,
            default=CrawlJob.SourceChoices.CAP,
            choices=CrawlJob.SourceChoices.values,
            help="Which upstream source to crawl.",
        )

    def handle(self, *args, **options):
        destination = Path(options["destination"]) if options["destination"] else None
        summary = ProtocolIngestionPipeline().run(
            limit=options["limit"],
            destination_root=destination,
            crawl_source=options["source"],
        )
        self.stdout.write(self.style.SUCCESS("CAP protocol import completed."))
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")
