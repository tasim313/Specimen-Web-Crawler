from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from pathology.models import CrawlJob, Organ, Specimen
from pathology.services.jobs import CrawlJobService
from pathology.services.normalizers import (
    build_specimen_name,
    infer_organ_name,
    normalize_specimen_size,
    normalize_specimen_type,
)
from pathology.services.pagination import paginate_keyset
from pathology.services.pipeline import ProtocolIngestionPipeline
from pathology.services.types import ParsedSpecimenData


class NormalizerTests(TestCase):
    def test_specimen_type_normalization_is_case_insensitive(self):
        self.assertEqual(
            normalize_specimen_type("Procedure: core NEEDLE biopsy"),
            "Needle Biopsy",
        )

    def test_organ_inference_uses_keywords(self):
        self.assertEqual(
            infer_organ_name("Breast Invasive Carcinoma, Resection"),
            "Breast",
        )

    def test_specimen_size_normalization_prefers_clinical_buckets(self):
        self.assertEqual(
            normalize_specimen_size("core needle biopsy", "Needle Biopsy", "Breast"),
            "Small (Cylindrical cores)",
        )

    def test_build_specimen_name_produces_export_friendly_label(self):
        self.assertEqual(
            build_specimen_name(
                "Breast DCIS, Biopsy",
                "Breast",
                "Biopsy",
                "breast_dcis_biopsy",
            ),
            "Breast DCIS biopsy specimen",
        )


class PipelinePersistenceTests(TestCase):
    def test_upsert_uses_source_file_for_idempotency(self):
        pipeline = ProtocolIngestionPipeline(crawler=None)
        parsed = ParsedSpecimenData(
            specimen_name="Breast Invasive Carcinoma",
            organ_name="Breast",
            specimen_type="Resection",
            specimen_size="3.2 cm",
            source_file=Path("data/breast/breast_invasive_resection.pdf"),
        )
        parsed_docx = ParsedSpecimenData(
            specimen_name="Breast Invasive Carcinoma",
            organ_name="Breast",
            specimen_type="Resection",
            specimen_size="3.2 cm",
            source_file=Path("data/breast/breast_invasive_resection.docx"),
        )

        first = pipeline._upsert_specimen(parsed)
        second = pipeline._upsert_specimen(parsed_docx)

        self.assertEqual(first, "created")
        self.assertEqual(second, "updated")
        self.assertEqual(Organ.objects.count(), 1)
        self.assertEqual(Specimen.objects.count(), 1)
        self.assertTrue(
            Specimen.objects.get().source_file.endswith(".docx")
        )


class CrawlJobTests(TestCase):
    @patch("pathology.services.jobs.subprocess.Popen")
    def test_start_job_spawns_background_process(self, mock_popen):
        mock_popen.return_value.pid = 4321
        job = CrawlJob.objects.create(name="CAP Crawl", limit=2)

        CrawlJobService().start_job(job)

        job.refresh_from_db()
        self.assertEqual(job.process_id, 4321)
        self.assertEqual(job.status, CrawlJob.Status.PENDING)
        self.assertFalse(job.stop_requested)

    def test_request_stop_marks_job(self):
        job = CrawlJob.objects.create(
            name="CAP Crawl",
            status=CrawlJob.Status.RUNNING,
        )

        CrawlJobService().request_stop(job)

        job.refresh_from_db()
        self.assertTrue(job.stop_requested)
        self.assertEqual(job.status, CrawlJob.Status.STOP_REQUESTED)


class KeysetPaginationTests(TestCase):
    def setUp(self):
        organ = Organ.objects.create(name="Breast")
        for index in range(1, 6):
            Specimen.objects.create(
                organ=organ,
                specimen_name=f"Specimen {index}",
                specimen_type="Biopsy",
                specimen_size="Small",
                source_file=f"breast/specimen_{index}.docx",
            )

    def test_first_page_returns_next_cursor(self):
        page = paginate_keyset(Specimen.objects.all(), page_size=2)
        self.assertEqual(len(page.items), 2)
        self.assertTrue(page.has_next)
        self.assertIsNotNone(page.next_cursor)

    def test_next_page_uses_after_cursor(self):
        first = paginate_keyset(Specimen.objects.all(), page_size=2)
        second = paginate_keyset(
            Specimen.objects.all(),
            page_size=2,
            after=first.next_cursor,
        )
        self.assertEqual(len(second.items), 2)
        self.assertTrue(second.has_prev)
