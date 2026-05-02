from __future__ import annotations

import csv

from django.core.management.base import BaseCommand

from pathology.models import Specimen


class Command(BaseCommand):
    help = "Export specimens to CSV in the format: Organ Name, Specimen Name, Specimen Type, Specimen Size."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=str,
            default="specimens_export.csv",
            help="Output CSV file path.",
        )

    def handle(self, *args, **options):
        output_path = options["output"]
        queryset = Specimen.objects.select_related("organ").order_by(
            "organ__name",
            "specimen_name",
        )

        with open(output_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["Organ Name", "Specimen Name", "Specimen Type", "Specimen Size"]
            )
            for specimen in queryset:
                writer.writerow(
                    [
                        specimen.organ.name,
                        specimen.specimen_name,
                        specimen.specimen_type,
                        specimen.specimen_size or "",
                    ]
                )

        self.stdout.write(
            self.style.SUCCESS(f"Exported {queryset.count()} specimens to {output_path}")
        )
