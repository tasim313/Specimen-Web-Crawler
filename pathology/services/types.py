from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ProtocolDocumentLink:
    category: str
    protocol_name: str
    file_url: str
    file_type: str


@dataclass(slots=True)
class ParsedSpecimenData:
    specimen_name: str
    organ_name: str
    specimen_type: str
    specimen_size: str
    source_file: Path
