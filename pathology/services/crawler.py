from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings

from .normalizers import clean_whitespace, slugify_category
from .types import ProtocolDocumentLink

logger = logging.getLogger("pathology.crawler")


class CAPCrawler:
    def __init__(self, base_url: str | None = None, headless: bool = True):
        self.base_url = base_url or settings.CAP_PROTOCOL_INDEX_URL
        self.headless = headless

    def collect_document_links(self) -> list[ProtocolDocumentLink]:
        html = self._fetch_page_html()
        soup = BeautifulSoup(html, "html.parser")
        return self._parse_links_from_html(soup)

    def download_documents(
        self,
        documents: list[ProtocolDocumentLink],
        destination_root: Path | None = None,
        should_stop=None,
    ) -> list[Path]:
        destination_root = destination_root or settings.DATA_DIR
        downloaded_files: list[Path] = []
        seen_destinations: set[Path] = set()

        for document in documents:
            if should_stop and should_stop():
                break
            destination = self.download_document(
                document,
                destination_root=destination_root,
                should_stop=should_stop,
                seen_destinations=seen_destinations,
            )
            if destination is not None:
                downloaded_files.append(destination)

        return downloaded_files

    def download_document(
        self,
        document: ProtocolDocumentLink,
        *,
        destination_root: Path | None = None,
        should_stop=None,
        seen_destinations: set[Path] | None = None,
    ) -> Path | None:
        destination_root = destination_root or settings.DATA_DIR
        category_dir = destination_root / slugify_category(document.category)
        category_dir.mkdir(parents=True, exist_ok=True)
        destination = category_dir / self._filename_for(document)

        if seen_destinations is not None:
            if destination in seen_destinations:
                logger.info("Skipping duplicate destination in same crawl: %s", destination)
                return None
            seen_destinations.add(destination)

        if destination.exists():
            logger.info("Skipping existing file: %s", destination)
            time.sleep(random.uniform(2, 5))
            return destination

        for attempt in range(1, 4):
            if should_stop and should_stop():
                return None
            try:
                self._download_file(document.file_url, destination)
                logger.info("Downloaded %s", destination)
                time.sleep(random.uniform(2, 5))
                return destination
            except Exception:
                logger.exception(
                    "Download failed for %s (attempt %s/3)",
                    document.file_url,
                    attempt,
                )
                if attempt == 3 and destination.exists():
                    destination.unlink(missing_ok=True)
            time.sleep(random.uniform(2, 5))

        logger.error("Giving up on %s after 3 attempts", document.file_url)
        return None

    # def _fetch_page_html(self) -> str:
    #     from playwright.sync_api import sync_playwright

    #     with sync_playwright() as playwright:
    #         browser = playwright.chromium.launch(
    #             headless=self.headless,
    #             chromium_sandbox=False,
    #             args=["--disable-setuid-sandbox", "--no-sandbox"],
    #         )
    #         page = browser.new_page()
    #         page.goto(self.base_url, wait_until="networkidle", timeout=120000)
    #         page.wait_for_timeout(2000)
    #         html = page.content()
    #         browser.close()
    #     return html

    def _fetch_page_html(self) -> str:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.headless,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                page = browser.new_page()
                page.goto(self.base_url, wait_until="networkidle", timeout=120000)
                html = page.content()
                browser.close()
                return html

        except Exception as e:
            logger.exception("Playwright failed, falling back to requests: %s", e)
            response = requests.get(self.base_url, timeout=60)
            response.raise_for_status()
            return response.text

    def _parse_links_from_html(self, soup: BeautifulSoup) -> list[ProtocolDocumentLink]:
        documents = self._parse_current_protocol_links(soup)
        if documents:
            logger.info("Collected %s current-version document links", len(documents))
            return documents

        documents = self._parse_links_from_tables(soup)
        logger.info("Collected %s document links from table fallback", len(documents))
        return documents

    def _parse_current_protocol_links(self, soup: BeautifulSoup) -> list[ProtocolDocumentLink]:
        section_heading = soup.find(
            lambda tag: getattr(tag, "name", None) in {"h2", "h3", "h4"}
            and clean_whitespace(tag.get_text(" ", strip=True)).lower()
            == "cancer reporting and biomarker reporting protocols"
        )
        if section_heading is None:
            return []

        documents: list[ProtocolDocumentLink] = []
        seen: set[tuple[str, str]] = set()
        current_category = "general"
        current_protocol = ""

        for tag in section_heading.find_all_next():
            tag_name = getattr(tag, "name", None)
            if tag is not section_heading and tag_name in {"h1", "h2"}:
                break

            text = clean_whitespace(tag.get_text(" ", strip=True))
            if not text:
                continue

            if tag_name == "h3":
                current_category = text
                current_protocol = ""
                continue

            if "current version" in text.lower():
                current_protocol = re.sub(
                    r"\s*current version\s*$",
                    "",
                    text,
                    flags=re.IGNORECASE,
                ).strip(" :")
                continue

            if "previous version" in text.lower():
                current_protocol = ""
                continue

            if tag_name != "a" or not current_protocol or not tag.get("href"):
                continue

            file_type = self._detect_file_type(tag["href"])
            if file_type is None or text.lower() not in {"pdf", "word"}:
                continue

            file_url = urljoin(self.base_url, tag["href"])
            key = (current_protocol, file_url)
            if key in seen:
                continue

            seen.add(key)
            documents.append(
                ProtocolDocumentLink(
                    category=current_category,
                    protocol_name=current_protocol,
                    file_url=file_url,
                    file_type=file_type,
                )
            )

        return documents

    def _parse_links_from_tables(self, soup: BeautifulSoup) -> list[ProtocolDocumentLink]:
        documents: list[ProtocolDocumentLink] = []
        seen: set[tuple[str, str]] = set()
        for table in soup.find_all("table"):
            category = self._find_category_for_table(table)
            if not category or category.lower() == "latest news and resources":
                continue

            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue

                protocol_name = clean_whitespace(cells[0].get_text(" ", strip=True))
                if not protocol_name:
                    continue

                for anchor in row.find_all("a", href=True):
                    href = anchor["href"]
                    file_type = self._detect_file_type(href)
                    if file_type is None:
                        continue

                    file_url = urljoin(self.base_url, href)
                    key = (protocol_name, file_url)
                    if key in seen:
                        continue

                    seen.add(key)
                    documents.append(
                        ProtocolDocumentLink(
                            category=category,
                            protocol_name=protocol_name,
                            file_url=file_url,
                            file_type=file_type,
                        )
                    )

        return documents

    def _find_category_for_table(self, table) -> str:
        heading = table.find_previous(["h2", "h3", "h4"])
        return clean_whitespace(heading.get_text(" ", strip=True)) if heading else "general"

    def _detect_file_type(self, href: str) -> str | None:
        href_lower = href.lower()
        if re.search(r"\.docx(?:$|\?)", href_lower):
            return "docx"
        if re.search(r"\.pdf(?:$|\?)", href_lower):
            return "pdf"
        return None

    def _filename_for(self, document: ProtocolDocumentLink) -> str:
        slug = slugify_category(document.protocol_name).replace("__", "_")
        parsed = urlparse(document.file_url)
        suffix = Path(parsed.path).suffix or f".{document.file_type}"
        return f"{slug}{suffix}"

    def _download_file(self, url: str, destination: Path) -> None:
        response = requests.get(url, timeout=120, stream=True)
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
