from __future__ import annotations

from django.core.management.base import BaseCommand

from pathology.models import CrawlJob


class Command(BaseCommand):
    help = "Create a crawl job that can later be started from Django Admin or another command."

    def add_arguments(self, parser):
        parser.add_argument("--name", type=str, default="")
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--destination", type=str, default="")
        parser.add_argument(
            "--source",
            type=str,
            default=CrawlJob.SourceChoices.CAP,
            choices=CrawlJob.SourceChoices.values,
        )

    def handle(self, *args, **options):
        job = CrawlJob.objects.create(
            name=options["name"],
            crawl_source=options["source"],
            limit=options["limit"],
            destination_dir=options["destination"],
        )
        self.stdout.write(self.style.SUCCESS(f"Created crawl job #{job.pk}"))
