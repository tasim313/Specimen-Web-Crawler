from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from django.test import TestCase

from pathology.models import CrawlJob, Organ, Specimen
from pathology.services.crawler import CAPCrawler, SourceUnavailable
from pathology.services.jobs import CrawlJobService, start_default_job_if_needed
from pathology.services.documents import _extract_laterality, _extract_site_name
from pathology.services.normalizers import (
    build_specimen_name,
    infer_organ_name,
    normalize_specimen_size,
    normalize_specimen_type,
)
from pathology.services.pagination import paginate_keyset
from pathology.services.pipeline import ProtocolIngestionPipeline
from pathology.services.types import ParsedSpecimenData, ProtocolDocumentLink


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

    def test_organ_inference_prefers_specific_keyword_over_partial_match(self):
        self.assertEqual(
            infer_organ_name(
                "Specimens from patients with carcinoma of the gallbladder",
                "Gastrointestinal",
                "gallbladder",
            ),
            "Gallbladder",
        )

    def test_organ_inference_uses_source_stem_before_broad_category_fallback(self):
        self.assertEqual(
            infer_organ_name(
                "Specimens from patients with thymic tumors",
                "Thorax",
                "thymus",
            ),
            "Thymus",
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

    def test_extract_site_name_collects_tumor_site_options(self):
        content = "\n".join(
            [
                "Tumor Site",
                "___ Upper outer quadrant",
                "___ Lower outer quadrant",
                "___ Central",
                "Histologic Type",
            ]
        )
        self.assertEqual(
            _extract_site_name(content, "Breast"),
            "Upper outer quadrant; Lower outer quadrant; Central",
        )

    def test_extract_laterality_collects_laterality_options(self):
        content = "\n".join(
            [
                "Specimen Laterality",
                "___ Right",
                "___ Left",
                "___ Not specified",
                "Tumor Site",
            ]
        )
        self.assertEqual(
            _extract_laterality(content, ""),
            "Right; Left; Not specified",
        )


class CrawlerParsingTests(TestCase):
    def test_parser_prefers_current_version_links_from_live_page_structure(self):
        html = """
        <h2>Cancer Reporting and Biomarker Reporting Protocols</h2>
        <h3>Breast</h3>
        <p>Breast DCIS, Resection Current Version</p>
        <a href="https://documents.cap.org/protocols/Breast.DCIS_4.4.0.0.REL_CAPCP.pdf">PDF</a>
        <a href="https://documents.cap.org/protocols/Breast.DCIS_4.4.0.0.REL_CAPCP.docx">Word</a>
        <p>June 2021 Previous Version</p>
        <a href="https://documents.cap.org/protocols/Breast.DCIS_4.3.0.2.REL_CAPCP.pdf">2020</a>
        <h3>Endocrine</h3>
        <p>Thyroid Current Version</p>
        <a href="/protocols/thyroid-current.pdf">PDF</a>
        <a href="/protocols/thyroid-current.docx">Word</a>
        """
        crawler = CAPCrawler(base_url="https://www.cap.org/path/")

        documents = crawler._parse_links_from_html(BeautifulSoup(html, "html.parser"))

        self.assertEqual(len(documents), 4)
        self.assertEqual(documents[0].category, "Breast")
        self.assertEqual(documents[0].protocol_name, "Breast DCIS, Resection")
        self.assertTrue(documents[0].file_url.endswith(".pdf"))
        self.assertEqual(documents[1].file_type, "docx")
        self.assertEqual(documents[2].category, "Endocrine")
        self.assertEqual(
            documents[2].file_url,
            "https://www.cap.org/protocols/thyroid-current.pdf",
        )

    def test_download_documents_only_returns_each_destination_once(self):
        crawler = CAPCrawler()
        documents = [
            ProtocolDocumentLink(
                category="Breast",
                protocol_name="Breast DCIS, Resection",
                file_url="https://documents.cap.org/protocols/breast-current.pdf",
                file_type="pdf",
            ),
            ProtocolDocumentLink(
                category="Breast",
                protocol_name="Breast DCIS, Resection",
                file_url="https://documents.cap.org/protocols/breast-old.pdf",
                file_type="pdf",
            ),
        ]

        with patch("pathology.services.crawler.time.sleep"), patch.object(
            crawler,
            "_download_file",
        ) as mock_download:
            downloaded = crawler.download_documents(
                documents,
                destination_root=Path("tmp"),
            )

        self.assertEqual(len(downloaded), 1)
        self.assertEqual(mock_download.call_count, 1)


class PipelinePersistenceTests(TestCase):
    def test_upsert_uses_source_file_for_idempotency(self):
        pipeline = ProtocolIngestionPipeline(crawler=None)
        parsed = ParsedSpecimenData(
            specimen_name="Breast Invasive Carcinoma",
            organ_name="Breast",
            site_name="Upper outer quadrant",
            laterality="Right",
            specimen_type="Resection",
            specimen_size="3.2 cm",
            source_site="cap.org",
            source_file=Path("data/breast/breast_invasive_resection.pdf"),
        )
        parsed_docx = ParsedSpecimenData(
            specimen_name="Breast Invasive Carcinoma",
            organ_name="Breast",
            site_name="Upper outer quadrant",
            laterality="Right",
            specimen_type="Resection",
            specimen_size="3.2 cm",
            source_site="cap.org",
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
        self.assertEqual(Specimen.objects.get().site_name, "Upper outer quadrant")
        self.assertEqual(Specimen.objects.get().laterality, "Right")
        self.assertEqual(Specimen.objects.get().source_site, "cap.org")

    @patch("pathology.services.pipeline.parse_document")
    def test_pipeline_inserts_while_crawl_is_running(self, mock_parse_document):
        class StubCrawler:
            def collect_document_links(self):
                return [
                    ProtocolDocumentLink(
                        category="Breast",
                        protocol_name="Breast DCIS, Resection",
                        file_url="https://example.com/breast_dcis_resection.docx",
                        file_type="docx",
                    ),
                    ProtocolDocumentLink(
                        category="Endocrine",
                        protocol_name="Thyroid",
                        file_url="https://example.com/thyroid.docx",
                        file_type="docx",
                    ),
                ]

            def download_document(
                self,
                document,
                *,
                destination_root=None,
                should_stop=None,
                seen_destinations=None,
            ):
                destination_root = destination_root or Path("data")
                destination = (
                    destination_root
                    / document.category.lower().replace(" ", "_")
                    / f"{document.protocol_name.lower().replace(', ', '_').replace(' ', '_')}.docx"
                )
                if seen_destinations is not None:
                    seen_destinations.add(destination)
                return destination

        pipeline = ProtocolIngestionPipeline(crawler=StubCrawler())
        mock_parse_document.side_effect = [
            ParsedSpecimenData(
                specimen_name="Breast DCIS resection specimen",
                organ_name="Breast",
                site_name="Upper outer quadrant",
                laterality="Right",
                specimen_type="Resection",
                specimen_size="Large",
                source_site="cap.org",
                source_file=Path("data/breast/breast_dcis_resection.docx"),
            ),
            ParsedSpecimenData(
                specimen_name="Thyroid specimen",
                organ_name="Thyroid",
                site_name="Thyroid",
                laterality="",
                specimen_type="Unknown",
                specimen_size="",
                source_site="cap.org",
                source_file=Path("data/endocrine/thyroid.docx"),
            ),
        ]
        progress = []

        summary = pipeline.run(progress_callback=lambda item: progress.append(item.copy()))

        self.assertEqual(summary["created"], 2)
        self.assertEqual(Organ.objects.count(), 2)
        self.assertEqual(Specimen.objects.count(), 2)
        self.assertTrue(any(item["created"] == 1 for item in progress))
        self.assertTrue(any(item["created"] == 2 for item in progress))

    def test_upsert_moves_existing_record_to_correct_organ_when_source_matches(self):
        old_organ = Organ.objects.create(name="Endocrine")
        Specimen.objects.create(
            organ=old_organ,
            specimen_name="Specimens from with of the Gallbladder",
            specimen_type="Unknown",
            specimen_size="",
            source_file="gastrointestinal/gallbladder.docx",
        )
        pipeline = ProtocolIngestionPipeline(crawler=None)
        parsed = ParsedSpecimenData(
            specimen_name="Gallbladder resection specimen",
            organ_name="Gallbladder",
            site_name="Gallbladder",
            laterality="",
            specimen_type="Resection",
            specimen_size="Medium (Length/Diameter)",
            source_site="cap.org",
            source_file=Path("data/gastrointestinal/gallbladder.docx"),
        )

        result = pipeline._upsert_specimen(parsed)

        self.assertEqual(result, "updated")
        specimen = Specimen.objects.get(source_file="gastrointestinal/gallbladder.docx")
        self.assertEqual(specimen.organ.name, "Gallbladder")
        self.assertEqual(specimen.specimen_type, "Resection")

    @patch("pathology.services.pipeline.PathologyOutlinesCrawler.ensure_crawlable")
    def test_pipeline_pathology_outlines_source_raises_real_source_error(self, mock_ensure):
        mock_ensure.side_effect = SourceUnavailable("blocked")
        pipeline = ProtocolIngestionPipeline(crawler=None)

        with self.assertRaises(SourceUnavailable):
            pipeline.run(crawl_source="pathologyoutlines.com")

    @patch("pathology.services.pipeline.PathologyOutlinesCrawler.ensure_crawlable")
    @patch("pathology.services.pipeline.CAPCrawler.collect_document_links")
    def test_pipeline_both_sources_continues_with_cap_when_pathology_outlines_blocked(
        self,
        mock_collect,
        mock_ensure,
    ):
        mock_ensure.side_effect = SourceUnavailable("blocked")
        mock_collect.return_value = []
        pipeline = ProtocolIngestionPipeline(crawler=CAPCrawler())

        summary = pipeline.run(crawl_source="both")

        self.assertEqual(summary["links"], 0)


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

    @patch("pathology.services.jobs.CrawlJobService.start_job")
    def test_auto_start_creates_unlimited_default_job_when_empty(self, mock_start_job):
        mock_start_job.side_effect = lambda job: job

        job = start_default_job_if_needed()

        self.assertIsNotNone(job)
        created_job = CrawlJob.objects.get(name="Automatic CAP Crawl")
        self.assertIsNone(created_job.limit)
        self.assertTrue(created_job.destination_dir.endswith("/data"))
        self.assertEqual(created_job.crawl_source, "cap.org")
        mock_start_job.assert_called_once_with(created_job)

    @patch("pathology.services.jobs.CrawlJobService.start_job")
    def test_auto_start_skips_completed_job_when_specimens_exist(self, mock_start_job):
        organ = Organ.objects.create(name="Breast")
        Specimen.objects.create(
            organ=organ,
            specimen_name="Breast specimen",
            specimen_type="Biopsy",
            specimen_size="Small",
            source_file="breast/specimen.docx",
        )
        CrawlJob.objects.create(
            name="Automatic CAP Crawl",
            status=CrawlJob.Status.COMPLETED,
            destination_dir="data",
        )

        job = start_default_job_if_needed()

        self.assertIsNone(job)
        mock_start_job.assert_not_called()


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
