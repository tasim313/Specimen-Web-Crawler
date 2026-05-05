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

from .normalizers import (
    build_specimen_name,
    clean_whitespace,
    infer_organ_name,
    infer_specimen_type,
    normalize_specimen_size,
    slugify_category,
)
from .types import ParsedSpecimenData, ProtocolDocumentLink

logger = logging.getLogger("pathology.crawler")


class SourceUnavailable(RuntimeError):
    """Raised when an upstream source cannot be crawled from this environment."""


class CAPCrawler:
    source_site = "cap.org"

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
                    source_site=self.source_site,
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
                            source_site=self.source_site,
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


class PathologyOutlinesCrawler:
    source_site = "pathologyoutlines.com"
    base_url = "https://www.pathologyoutlines.com/"
    excluded_topic_prefixes = (
        "/topic/library",
        "/topic/covid",
    )
    excluded_chapter_paths = {
        "/",
        "/aboutus.html",
        "/authors",
        "/books",
        "/cme",
        "/conferences",
        "/contactus.html",
        "/crossword.html",
        "/directory",
        "/fellowships",
        "/grants.html",
        "/informatrics.html",
        "/jobs",
        "/monthlystats.php",
        "/privacy.html",
        "/review-questions",
        "/staging.html",
        "/subscribe.html",
        "/whoclassification.html",
    }

    def __init__(self, sitemap_url: str | None = None):
        self.sitemap_url = sitemap_url or settings.PATHOLOGY_OUTLINES_SITEMAP_URL

    def ensure_crawlable(self) -> None:
        sitemap_html = self._fetch_html(self.sitemap_url)
        if "503 Service Unavailable" in sitemap_html:
            raise SourceUnavailable(
                "Pathology Outlines returned 503 at sitemap page; source is blocked from this environment."
            )

        chapter_url = self._first_chapter_url(BeautifulSoup(sitemap_html, "html.parser"))
        if not chapter_url:
            raise SourceUnavailable(
                "Pathology Outlines sitemap did not expose chapter links that can be crawled."
            )

        chapter_html = self._fetch_html(chapter_url)
        if "503 Service Unavailable" in chapter_html:
            raise SourceUnavailable(
                "Pathology Outlines chapter content returned 503; source is blocked from this environment."
            )

    def collect_specimens(
        self,
        *,
        limit: int | None = None,
        should_stop=None,
    ) -> list[ParsedSpecimenData]:
        self.ensure_crawlable()
        sitemap_html = self._fetch_html(self.sitemap_url)
        sitemap_soup = BeautifulSoup(sitemap_html, "xml")
        chapter_urls = self._chapter_urls_from_sitemap(sitemap_soup)

        specimens: list[ParsedSpecimenData] = []
        seen_topic_urls: set[str] = set()

        for chapter_url in chapter_urls:
            if should_stop and should_stop():
                break
            if limit is not None and len(specimens) >= limit:
                break

            chapter_html = self._fetch_html(chapter_url)
            if "503 Service Unavailable" in chapter_html:
                logger.warning("Skipping blocked chapter page: %s", chapter_url)
                continue

            chapter_soup = BeautifulSoup(chapter_html, "html.parser")
            chapter_name = self._chapter_name(chapter_url, chapter_soup)

            for topic_url in self._topic_urls_from_chapter(chapter_soup):
                if should_stop and should_stop():
                    break
                if limit is not None and len(specimens) >= limit:
                    break
                if topic_url in seen_topic_urls:
                    continue
                seen_topic_urls.add(topic_url)

                try:
                    topic_html = self._fetch_html(topic_url)
                except Exception:
                    logger.exception("Failed to fetch topic page: %s", topic_url)
                    continue

                if "503 Service Unavailable" in topic_html:
                    logger.warning("Skipping blocked topic page: %s", topic_url)
                    continue

                parsed = self._parse_topic_page(topic_html, topic_url, chapter_name)
                if parsed is not None:
                    specimens.append(parsed)

        logger.info("Collected %s Pathology Outlines topics", len(specimens))
        return specimens

    def _fetch_html(self, url: str) -> str:
        response = requests.get(
            url,
            timeout=60,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
        return response.text

    def _first_chapter_url(self, soup: BeautifulSoup) -> str:
        for url in self._chapter_urls_from_sitemap(soup):
            if url.endswith(("breast.html", "colon.html", "ovarytumor.html", "lung.html")):
                return url
        for url in self._chapter_urls_from_sitemap(soup):
            return url
        return ""

    def _chapter_urls_from_sitemap(self, soup: BeautifulSoup) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()

        for loc in soup.find_all("loc"):
            href = clean_whitespace(loc.get_text(" ", strip=True))
            if not href.startswith(self.base_url):
                continue

            parsed = urlparse(href)
            path = parsed.path
            if not path or "/topic/" in path:
                continue
            if not path.endswith(".html"):
                continue
            if path in self.excluded_chapter_paths:
                continue
            if href in seen:
                continue

            seen.add(href)
            urls.append(href)

        return urls

    def _topic_urls_from_chapter(self, soup: BeautifulSoup) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = urljoin(self.base_url, anchor["href"])
            parsed = urlparse(href)
            if parsed.netloc != urlparse(self.base_url).netloc:
                continue
            if not parsed.path.startswith("/topic/") or not parsed.path.endswith(".html"):
                continue
            if any(parsed.path.startswith(prefix) for prefix in self.excluded_topic_prefixes):
                continue
            if href in seen:
                continue

            seen.add(href)
            urls.append(href)

        return urls

    def _chapter_name(self, chapter_url: str, soup: BeautifulSoup) -> str:
        for selector in ("h1", "meta[property='og:title']", "title"):
            tag = soup.select_one(selector)
            if tag is None:
                continue
            text = tag.get("content", "") if tag.name == "meta" else tag.get_text(" ", strip=True)
            cleaned = self._clean_page_title(text)
            if cleaned and "503 Service Unavailable" not in cleaned:
                return cleaned

        stem = Path(urlparse(chapter_url).path).stem
        return clean_whitespace(stem.replace("_", " ").replace("-", " ").title())

    def _parse_topic_page(
        self,
        html: str,
        topic_url: str,
        chapter_name: str,
    ) -> ParsedSpecimenData | None:
        soup = BeautifulSoup(html, "html.parser")
        title = self._extract_topic_title(soup, topic_url)
        if not title:
            return None

        text_content = self._extract_topic_text(soup)
        organ_name = infer_organ_name(
            title,
            fallback=chapter_name,
            source_stem=Path(urlparse(topic_url).path).stem,
        )
        specimen_type = infer_specimen_type(title, body_excerpt=text_content[:4000])
        specimen_name = build_specimen_name(
            title,
            organ_name,
            specimen_type,
            source_stem=Path(urlparse(topic_url).path).stem,
        )
        site_name = self._extract_site_name_from_topic(text_content, organ_name)
        laterality = self._extract_laterality_from_topic(text_content, site_name)
        specimen_size = normalize_specimen_size(
            f"{title}\n{text_content[:2000]}",
            specimen_type,
            organ_name,
        )

        return ParsedSpecimenData(
            specimen_name=specimen_name,
            organ_name=organ_name,
            site_name=site_name,
            laterality=laterality,
            specimen_type=specimen_type,
            specimen_size=specimen_size,
            source_site=self.source_site,
            source_file=Path(f"pathologyoutlines{urlparse(topic_url).path}"),
        )

    def _extract_topic_title(self, soup: BeautifulSoup, topic_url: str) -> str:
        for selector in ("h1", "meta[property='og:title']", "title"):
            tag = soup.select_one(selector)
            if tag is None:
                continue
            text = tag.get("content", "") if tag.name == "meta" else tag.get_text(" ", strip=True)
            cleaned = self._clean_page_title(text)
            if cleaned and "503 Service Unavailable" not in cleaned:
                return cleaned

        stem = Path(urlparse(topic_url).path).stem
        return clean_whitespace(stem.replace("_", " ").replace("-", " ").title())

    def _clean_page_title(self, value: str) -> str:
        text = clean_whitespace(value)
        text = re.sub(r"^Pathology Outlines\s*-\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^Topic\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\.html?$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*\|\s*Pathology Outlines.*$", "", text, flags=re.IGNORECASE)
        return clean_whitespace(text)

    def _extract_topic_text(self, soup: BeautifulSoup) -> str:
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        chunks: list[str] = []
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "dt", "dd"]):
            text = clean_whitespace(tag.get_text(" ", strip=True))
            if not text:
                continue
            if text in {"Menu", "Jobs", "Books", "Contact Us"}:
                continue
            chunks.append(text)
        return "\n".join(chunks)

    def _extract_site_name_from_topic(self, text_content: str, organ_name: str) -> str:
        lines = [clean_whitespace(line) for line in text_content.splitlines() if clean_whitespace(line)]
        for heading in ("site", "sites", "origin", "location", "organ"):
            section = self._extract_text_section(lines, heading)
            if section:
                values = self._split_section_values(section)
                if values:
                    return "; ".join(values[:6])
        return organ_name

    def _extract_laterality_from_topic(self, text_content: str, site_name: str) -> str:
        haystack = f"{text_content}\n{site_name}".lower()
        matches = []
        for label in ("Right", "Left", "Bilateral"):
            if label.lower() in haystack:
                matches.append(label)
        return "; ".join(matches)

    def _extract_text_section(self, lines: list[str], heading: str) -> str:
        target = heading.lower()
        for index, line in enumerate(lines):
            normalized = line.lower().rstrip(":")
            if normalized != target:
                continue

            section_lines: list[str] = []
            for candidate in lines[index + 1:index + 8]:
                candidate_lower = candidate.lower().rstrip(":")
                if candidate_lower in {
                    "definition / general",
                    "essential features",
                    "terminology",
                    "pathophysiology",
                    "gross description",
                    "microscopic (histologic) description",
                    "treatment",
                    "prognostic factors",
                    "staging",
                    "cytology description",
                    "positive stains",
                    "negative stains",
                }:
                    break
                if len(candidate) <= 2:
                    continue
                section_lines.append(candidate)
            if section_lines:
                return "\n".join(section_lines)
        return ""

    def _split_section_values(self, value: str) -> list[str]:
        parts = re.split(r"\s*[;|]\s*|\n+|\s{2,}", value)
        cleaned: list[str] = []
        for part in parts:
            normalized = clean_whitespace(part).strip(" -,:")
            if not normalized:
                continue
            if normalized.lower() in {"site", "sites", "location", "organ"}:
                continue
            if normalized not in cleaned:
                cleaned.append(normalized)
        return cleaned
