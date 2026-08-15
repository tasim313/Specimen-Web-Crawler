from __future__ import annotations

import csv

from django.core.management.base import BaseCommand

from pathology.models import Specimen


class Command(BaseCommand):
    help = "Export specimens to CSV with specimen, procedure, source, and clinical applicability fields."

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
                [
                    "Organ Name",
                    "Specimen Name",
                    "Site Name",
                    "Laterality",
                    "Specimen Type",
                    "Specimen Size",
                    "Procedure Name",
                    "Is Biopsy",
                    "Is Resection",
                    "Is Cytology",
                    "Is Histopathology",
                    "Is IHC Applicable",
                    "Is Molecular Applicable",
                    "Source Site",
                    "Source File",
                ]
            )
            for specimen in queryset:
                writer.writerow(
                    [
                        specimen.organ.name,
                        specimen.specimen_name,
                        specimen.site_name,
                        specimen.laterality,
                        specimen.specimen_type,
                        specimen.specimen_size or "",
                        specimen.procedure_name,
                        specimen.is_biopsy,
                        specimen.is_resection,
                        specimen.is_cytology,
                        specimen.is_histopathology,
                        specimen.is_ihc_applicable,
                        specimen.is_molecular_applicable,
                        specimen.source_site,
                        specimen.source_file,
                    ]
                )

        self.stdout.write(
            self.style.SUCCESS(f"Exported {queryset.count()} specimens to {output_path}")
        )
