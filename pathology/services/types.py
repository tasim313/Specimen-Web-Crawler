from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ProtocolDocumentLink:
    category: str
    protocol_name: str
    file_url: str
    file_type: str
    source_site: str = "cap.org"


@dataclass(slots=True)
class ParsedSpecimenData:
    specimen_name: str
    organ_name: str
    site_name: str
    laterality: str
    specimen_type: str
    specimen_size: str
    source_site: str
    source_file: Path
    procedure_name: str = ""
    is_biopsy: bool = False
    is_resection: bool = False
    is_cytology: bool = False
    is_histopathology: bool = False
    is_ihc_applicable: bool = False
    is_molecular_applicable: bool = False
