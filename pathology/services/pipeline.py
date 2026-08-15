from __future__ import annotations

import logging
import re
from pathlib import Path

from django.conf import settings
from django.db import transaction

from pathology.models import Organ, Specimen

from .crawler import CAPCrawler, PathologyOutlinesCrawler, SourceUnavailable
from .documents import parse_document

logger = logging.getLogger("pathology.pipeline")


class CrawlStopped(Exception):
    """Raised when a crawl job is intentionally stopped."""


class ProtocolIngestionPipeline:
    def __init__(
        self,
        crawler: CAPCrawler | None = None,
        pathology_outlines_crawler: PathologyOutlinesCrawler | None = None,
    ):
        self.crawler = crawler or CAPCrawler()
        self.pathology_outlines_crawler = pathology_outlines_crawler or PathologyOutlinesCrawler()

    def run(
        self,
        *,
        limit: int | None = None,
        destination_root: Path | None = None,
        crawl_source: str = "cap.org",
        should_stop=None,
        progress_callback=None,
    ) -> dict[str, int]:
        def emit(summary: dict[str, int]) -> None:
            if progress_callback:
                progress_callback(summary)

        def empty_summary() -> dict[str, int]:
            return {
                "links": 0,
                "files": 0,
                "created": 0,
                "updated": 0,
                "skipped": 0,
            }

        def merge_summary(
            left: dict[str, int],
            right: dict[str, int],
        ) -> dict[str, int]:
            return {
                key: left.get(key, 0) + right.get(key, 0)
                for key in {"links", "files", "created", "updated", "skipped"}
            }

        if should_stop and should_stop():
            raise CrawlStopped("Crawl was stopped before it started.")

        summary = empty_summary()
        remaining_limit = limit

        if crawl_source in {"cap.org", "both"}:
            cap_summary = self._run_cap_ingestion(
                limit=remaining_limit,
                destination_root=destination_root,
                should_stop=should_stop,
                progress_callback=lambda partial: emit(merge_summary(summary, partial)),
            )
            summary = merge_summary(summary, cap_summary)
            if remaining_limit is not None:
                remaining_limit = max(remaining_limit - cap_summary["files"], 0)

        if crawl_source in {"pathologyoutlines.com", "both"}:
            try:
                pathout_summary = self._run_pathology_outlines_ingestion(
                    limit=remaining_limit,
                    should_stop=should_stop,
                    progress_callback=lambda partial: emit(merge_summary(summary, partial)),
                )
                summary = merge_summary(summary, pathout_summary)
            except SourceUnavailable:
                if crawl_source == "pathologyoutlines.com":
                    raise
                logger.exception(
                    "Pathology Outlines source is unavailable; continuing with CAP only."
                )

        return summary

    def _run_cap_ingestion(
        self,
        *,
        limit: int | None,
        destination_root: Path | None,
        should_stop,
        progress_callback,
    ) -> dict[str, int]:
        cap_root = destination_root or settings.DATA_DIR
        try:
            links = self.crawler.collect_document_links()
        except Exception:
            logger.exception(
                "CAP live index is unavailable; importing cached CAP protocol files from %s.",
                cap_root,
            )
            return self._run_cached_cap_ingestion(
                limit=limit,
                destination_root=cap_root,
                should_stop=should_stop,
                progress_callback=progress_callback,
            )

        if not links:
            logger.warning(
                "CAP live index returned no document links; importing cached CAP protocol files from %s.",
                cap_root,
            )
            return self._run_cached_cap_ingestion(
                limit=limit,
                destination_root=cap_root,
                should_stop=should_stop,
                progress_callback=progress_callback,
            )

        if limit is not None:
            links = links[:limit]
        progress_callback(self._summary(len(links), 0, 0, 0, 0))
        if should_stop and should_stop():
            raise CrawlStopped("Crawl was stopped before downloading documents.")

        created = 0
        updated = 0
        skipped = 0
        files_downloaded = 0
        seen_destinations: set[Path] = set()

        for document in links:
            if should_stop and should_stop():
                raise CrawlStopped("Crawl was stopped while processing documents.")
            file_path = self.crawler.download_document(
                document,
                destination_root=destination_root or settings.DATA_DIR,
                should_stop=should_stop,
                seen_destinations=seen_destinations,
            )
            if file_path is None:
                continue

            files_downloaded += 1
            category = file_path.parent.name
            parsed = parse_document(Path(file_path), category)
            if not parsed:
                skipped += 1
                progress_callback(
                    {
                        "links": len(links),
                        "files": files_downloaded,
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

            progress_callback(
                {
                    "links": len(links),
                    "files": files_downloaded,
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                }
            )

        return {
            "links": len(links),
            "files": files_downloaded,
            "created": created,
            "updated": updated,
            "skipped": skipped,
        }

    def _run_cached_cap_ingestion(
        self,
        *,
        limit: int | None,
        destination_root: Path,
        should_stop,
        progress_callback,
    ) -> dict[str, int]:
        files = self._cached_cap_files(destination_root)
        if limit is not None:
            files = files[:limit]

        progress_callback(self._summary(len(files), 0, 0, 0, 0))
        if not files:
            logger.warning("No cached CAP protocol files found in %s.", destination_root)

        created = 0
        updated = 0
        skipped = 0
        processed = 0

        for file_path in files:
            if should_stop and should_stop():
                raise CrawlStopped("Crawl was stopped while processing cached CAP files.")
            processed += 1
            parsed = parse_document(file_path, file_path.parent.name)
            if not parsed:
                skipped += 1
                progress_callback(
                    self._summary(len(files), processed, created, updated, skipped)
                )
                continue

            status = self._upsert_specimen(parsed)
            if status == "created":
                created += 1
            elif status == "updated":
                updated += 1
            else:
                skipped += 1
            progress_callback(
                self._summary(len(files), processed, created, updated, skipped)
            )

        return self._summary(len(files), processed, created, updated, skipped)

    def _cached_cap_files(self, destination_root: Path) -> list[Path]:
        if not destination_root.exists():
            return []
        return sorted(
            file_path
            for file_path in destination_root.rglob("*")
            if file_path.suffix.lower() in {".docx", ".pdf"}
        )

    def _run_pathology_outlines_ingestion(
        self,
        *,
        limit: int | None,
        should_stop,
        progress_callback,
    ) -> dict[str, int]:
        specimens = self.pathology_outlines_crawler.collect_specimens(
            limit=limit,
            should_stop=should_stop,
        )
        progress_callback(
            {
                "links": len(specimens),
                "files": 0,
                "created": 0,
                "updated": 0,
                "skipped": 0,
            }
        )

        created = 0
        updated = 0
        skipped = 0
        processed = 0

        for parsed in specimens:
            if should_stop and should_stop():
                raise CrawlStopped("Crawl was stopped while processing Pathology Outlines topics.")
            processed += 1
            status = self._upsert_specimen(parsed)
            if status == "created":
                created += 1
            elif status == "updated":
                updated += 1
            else:
                skipped += 1
            progress_callback(
                {
                    "links": len(specimens),
                    "files": processed,
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                }
            )

        return {
            "links": len(specimens),
            "files": processed,
            "created": created,
            "updated": updated,
            "skipped": skipped,
        }

    def _summary(
        self,
        links: int,
        files: int,
        created: int,
        updated: int,
        skipped: int,
    ) -> dict[str, int]:
        return {
            "links": links,
            "files": files,
            "created": created,
            "updated": updated,
            "skipped": skipped,
        }

    @transaction.atomic
    def _upsert_specimen(self, parsed) -> str:
        organ, _ = Organ.objects.get_or_create(name=parsed.organ_name)
        relative_source = self._relative_source_path(parsed.source_file)
        relative_stem = Path(relative_source).with_suffix("").as_posix()
        specimen = Specimen.objects.filter(source_file=relative_source).first()
        if specimen is None:
            for candidate in Specimen.objects.all():
                candidate_stem = Path(candidate.source_file).with_suffix("").as_posix()
                if candidate_stem == relative_stem:
                    specimen = candidate
                    break

        if specimen is None:
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
                site_name=parsed.site_name,
                laterality=parsed.laterality,
                specimen_type=parsed.specimen_type,
                specimen_size=parsed.specimen_size or "",
                procedure_name=parsed.procedure_name,
                is_biopsy=parsed.is_biopsy,
                is_resection=parsed.is_resection,
                is_cytology=parsed.is_cytology,
                is_histopathology=parsed.is_histopathology,
                is_ihc_applicable=parsed.is_ihc_applicable,
                is_molecular_applicable=parsed.is_molecular_applicable,
                source_site=parsed.source_site,
                source_file=relative_source,
            )
            logger.info("Created specimen record for %s", specimen.source_file)
            return "created"

        if self._should_update_existing(specimen, parsed, relative_source):
            specimen.organ = organ
            if self._source_has_rich_fields(relative_source):
                specimen.specimen_name = parsed.specimen_name
                specimen.site_name = parsed.site_name
                specimen.laterality = parsed.laterality
            specimen.specimen_type = parsed.specimen_type
            specimen.specimen_size = parsed.specimen_size or specimen.specimen_size
            specimen.procedure_name = parsed.procedure_name or specimen.procedure_name
            specimen.is_biopsy = parsed.is_biopsy
            specimen.is_resection = parsed.is_resection
            specimen.is_cytology = parsed.is_cytology
            specimen.is_histopathology = parsed.is_histopathology
            specimen.is_ihc_applicable = parsed.is_ihc_applicable
            specimen.is_molecular_applicable = parsed.is_molecular_applicable
            specimen.source_site = parsed.source_site
            specimen.source_file = relative_source
            specimen.save(
                update_fields=[
                    "organ",
                    "specimen_name",
                    "site_name",
                    "laterality",
                    "specimen_type",
                    "specimen_size",
                    "procedure_name",
                    "is_biopsy",
                    "is_resection",
                    "is_cytology",
                    "is_histopathology",
                    "is_ihc_applicable",
                    "is_molecular_applicable",
                    "source_site",
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

    def _relative_source_path(self, source_file: Path) -> str:
        source_path = Path(source_file)

        try:
            return source_path.relative_to(settings.DATA_DIR).as_posix()
        except ValueError:
            pass

        parts = source_path.parts
        if parts and parts[0] == "data":
            return Path(*parts[1:]).as_posix()
        if parts and parts[0] == "pathologyoutlines":
            return source_path.as_posix()
        if len(source_path.parents) > 1:
            return source_path.relative_to(source_path.parents[1]).as_posix()
        return source_path.as_posix()

    def _should_update_existing(self, specimen, parsed, relative_source: str) -> bool:
        existing_is_pdf = specimen.source_file.lower().endswith(".pdf")
        new_has_rich_fields = self._source_has_rich_fields(relative_source)

        return any(
            [
                specimen.organ.name != parsed.organ_name,
                specimen.specimen_type == "Unknown" and parsed.specimen_type != "Unknown",
                not specimen.specimen_size and bool(parsed.specimen_size),
                specimen.specimen_size != (parsed.specimen_size or specimen.specimen_size),
                specimen.procedure_name != (parsed.procedure_name or specimen.procedure_name),
                specimen.is_biopsy != parsed.is_biopsy,
                specimen.is_resection != parsed.is_resection,
                specimen.is_cytology != parsed.is_cytology,
                specimen.is_histopathology != parsed.is_histopathology,
                specimen.is_ihc_applicable != parsed.is_ihc_applicable,
                specimen.is_molecular_applicable != parsed.is_molecular_applicable,
                specimen.site_name != parsed.site_name and bool(parsed.site_name),
                specimen.laterality != parsed.laterality and bool(parsed.laterality),
                specimen.source_site != parsed.source_site,
                existing_is_pdf and new_has_rich_fields,
                specimen.specimen_name != parsed.specimen_name and new_has_rich_fields,
            ]
        )

    def _normalize_identity(self, specimen_name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", specimen_name.lower())

    def _source_has_rich_fields(self, relative_source: str) -> bool:
        return not relative_source.lower().endswith(".pdf")
