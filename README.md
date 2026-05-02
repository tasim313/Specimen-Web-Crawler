# CAP Pathology Data Pipeline

Backend-only Django pipeline for crawling CAP Cancer Protocol Templates, extracting structured specimen data, normalizing it, and storing it in SQLite with Django Admin management.

## Stack

- Crawling: Playwright
- HTML parsing: BeautifulSoup
- Document parsing: `python-docx`, `PyPDF2`, `pdfplumber` fallback
- Backend: Django
- Database: SQLite

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
python3 manage.py migrate
python3 manage.py createsuperuser
```

## Run the ingestion pipeline

```bash
python3 manage.py import_cap_protocols
```

For a smaller smoke run:

```bash
python3 manage.py import_cap_protocols --limit 4
```

Downloaded files are stored under `data/<category>/`.

## Admin

```bash
python3 manage.py runserver
```

Use Django Admin to search, filter, and export specimen records to CSV with columns:

- `Specimen Name`
- `Specimen Type`
- `Organ Name`
- `Specimen Size`
