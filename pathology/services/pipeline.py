from __future__ import annotations

import logging
import re
from pathlib import Path

from django.conf import settings
from django.db import transaction

from pathology.models import Organ, Specimen

from .crawler import CAPCrawler
from .documents import parse_document

logger = logging.getLogger("pathology.pipeline")


class CrawlStopped(Exception):
    """Raised when a crawl job is intentionally stopped."""


class ProtocolIngestionPipeline:
    def __init__(self, crawler: CAPCrawler | None = None):
        self.crawler = crawler or CAPCrawler()

    def run(
        self,
        *,
        limit: int | None = None,
        destination_root: Path | None = None,
        should_stop=None,
        progress_callback=None,
    ) -> dict[str, int]:
        def emit(summary: dict[str, int]) -> None:
            if progress_callback:
                progress_callback(summary)

        if should_stop and should_stop():
            raise CrawlStopped("Crawl was stopped before it started.")

        links = self.crawler.collect_document_links()
        if limit is not None:
            links = links[:limit]
        emit(
            {
                "links": len(links),
                "files": 0,
                "created": 0,
                "updated": 0,
                "skipped": 0,
            }
        )

        if should_stop and should_stop():
            raise CrawlStopped("Crawl was stopped before downloading documents.")

        files = self.crawler.download_documents(
            links,
            destination_root=destination_root or settings.DATA_DIR,
            should_stop=should_stop,
        )

        created = 0
        updated = 0
        skipped = 0

        for file_path in files:
            if should_stop and should_stop():
                raise CrawlStopped("Crawl was stopped while processing documents.")
            category = file_path.parent.name
            parsed = parse_document(Path(file_path), category)
            if not parsed:
                skipped += 1
                emit(
                    {
                        "links": len(links),
                        "files": len(files),
                        "created": created,
                        "updated": updated,
                        "skipped": skipped,
                    }
                )
                continue

            status = self._upsert_specimen(parsed)
            if status == "created":
                created += 1
            elif status == "updated":
                updated += 1
            else:
                skipped += 1

            emit(
                {
                    "links": len(links),
                    "files": len(files),
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                }
            )

        return {
            "links": len(links),
            "files": len(files),
            "created": created,
            "updated": updated,
            "skipped": skipped,
        }

    @transaction.atomic
    def _upsert_specimen(self, parsed) -> str:
        organ, _ = Organ.objects.get_or_create(name=parsed.organ_name)
        relative_source = str(parsed.source_file.relative_to(parsed.source_file.parents[1]))
        relative_stem = Path(relative_source).with_suffix("").as_posix()
        specimen = Specimen.objects.filter(
            organ=organ,
            specimen_name=parsed.specimen_name,
        ).first()
        if specimen is None:
            normalized_name = self._normalize_identity(parsed.specimen_name)
            for candidate in Specimen.objects.filter(organ=organ):
                if self._normalize_identity(candidate.specimen_name) == normalized_name:
                    specimen = candidate
                    break
                candidate_stem = Path(candidate.source_file).with_suffix("").as_posix()
                if candidate_stem == relative_stem:
                    specimen = candidate
                    break

        if specimen is None:
            specimen = Specimen.objects.create(
                organ=organ,
                specimen_name=parsed.specimen_name,
                specimen_type=parsed.specimen_type,
                specimen_size=parsed.specimen_size or "",
                source_file=relative_source,
            )
            logger.info("Created specimen record for %s", specimen.source_file)
            return "created"

        if self._should_update_existing(specimen, parsed, relative_source):
            if relative_source.lower().endswith(".docx"):
                specimen.specimen_name = parsed.specimen_name
            specimen.specimen_type = parsed.specimen_type
            specimen.specimen_size = parsed.specimen_size or specimen.specimen_size
            specimen.source_file = relative_source
            specimen.save(
                update_fields=[
                    "specimen_name",
                    "specimen_type",
                    "specimen_size",
                    "source_file",
                ]
            )
            logger.info("Updated specimen record for %s", specimen.source_file)
            return "updated"

        logger.info(
            "Skipped duplicate specimen variant for %s",
            relative_source,
        )
        return "skipped"

    def _should_update_existing(self, specimen, parsed, relative_source: str) -> bool:
        existing_is_pdf = specimen.source_file.lower().endswith(".pdf")
        new_is_docx = relative_source.lower().endswith(".docx")

        return any(
            [
                specimen.specimen_type == "Unknown" and parsed.specimen_type != "Unknown",
                not specimen.specimen_size and bool(parsed.specimen_size),
                specimen.specimen_size != (parsed.specimen_size or specimen.specimen_size),
                existing_is_pdf and new_is_docx,
                specimen.specimen_name != parsed.specimen_name and new_is_docx,
            ]
        )

    def _normalize_identity(self, specimen_name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", specimen_name.lower())
