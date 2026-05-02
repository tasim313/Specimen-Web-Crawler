from __future__ import annotations

import re

from .constants import ORGAN_KEYWORDS, SPECIMEN_TYPE_MAP, STOPWORDS_IN_SPECIMEN_NAME


def slugify_category(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return normalized or "uncategorized"


def normalize_specimen_type(text: str) -> str:
    haystack = (text or "").lower()
    for needle, normalized in sorted(
        SPECIMEN_TYPE_MAP.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if needle in haystack:
            return normalized
    return "Unknown"


def infer_specimen_type(raw_title: str, procedure_block: str = "", body_excerpt: str = "") -> str:
    title = (raw_title or "").lower()
    procedure = (procedure_block or "").lower()
    excerpt = (body_excerpt or "").lower()

    if "punch" in title:
        return "Punch Biopsy"
    if "wide local excision" in title:
        return "Wide Excision"
    if "polyp" in title or "polypectomy" in title:
        return "Polypectomy"
    if "fine needle aspiration" in title:
        return "Fine Needle Aspiration"
    if "core needle" in title or "needle core" in title:
        return "Needle Biopsy"
    if "appendectomy" in title or "cholecystectomy" in title:
        return "Excision (Total)"
    if "hysterectomy" in title or "total mastectomy" in title:
        return "Resection (Total)"
    if "resection specimen" in title or "resection specimens" in title:
        return "Resection"
    if "resection" in title:
        return "Resection"
    if "excision" in title:
        return "Excision"
    if "biopsy" in title:
        return "Biopsy"

    return normalize_specimen_type("\n".join(part for part in (procedure, excerpt) if part))


def normalize_specimen_size(text: str, specimen_type: str, organ_name: str) -> str:
    haystack = (text or "").lower()
    organ_lower = (organ_name or "").lower()
    specimen_type_lower = (specimen_type or "").lower()

    if "punch biopsy" in specimen_type_lower or "punch" in haystack:
        return "Small (e.g., 3-4mm)"
    if "needle biopsy" in specimen_type_lower:
        return "Small (Cylindrical cores)"
    if "fine needle aspiration" in specimen_type_lower:
        return "Small (Cylindrical cores)"
    if "polypectomy" in specimen_type_lower or "polyp" in haystack:
        return "Small to Medium"
    if organ_lower in {"appendix", "gallbladder"}:
        return "Medium (Length/Diameter)"
    if "resection (total)" in specimen_type_lower:
        return "Large (Weight/Dimensions)" if organ_lower in {"uterus", "breast"} else "Large"
    if "wide excision" in specimen_type_lower:
        return "Large"
    if "resection" in specimen_type_lower:
        return "Large (Weight/Dimensions)" if organ_lower in {"uterus", "breast"} else "Large"
    if "excision" in specimen_type_lower:
        return "Medium"
    return ""


def infer_organ_name(specimen_name: str, fallback: str = "") -> str:
    haystack = f"{specimen_name} {fallback}".lower()
    for keyword, normalized in ORGAN_KEYWORDS.items():
        if keyword in haystack:
            return normalized
    return fallback or "Unknown"


def build_specimen_name(
    raw_title: str,
    organ_name: str,
    specimen_type: str,
    source_stem: str = "",
) -> str:
    cleaned_title = clean_whitespace(raw_title)
    descriptor = extract_protocol_descriptor(
        raw_title=cleaned_title,
        organ_name=organ_name,
        specimen_type=specimen_type,
        source_stem=source_stem,
    )

    if specimen_type == "Punch Biopsy":
        return _join_specimen_parts(organ_name, descriptor, "punch biopsy specimen")
    if specimen_type == "Needle Biopsy":
        return _join_specimen_parts(organ_name, descriptor, "needle biopsy specimen")
    if specimen_type == "Fine Needle Aspiration":
        return _join_specimen_parts(organ_name, descriptor, "fine needle aspiration specimen")
    if specimen_type == "Polypectomy":
        return _join_specimen_parts(organ_name, descriptor, "polypectomy specimen")
    if specimen_type == "Wide Excision":
        return _join_specimen_parts(organ_name, descriptor, "wide excision specimen")
    if specimen_type == "Excision (Total)":
        return _join_specimen_parts(organ_name, descriptor, "excision specimen")
    if specimen_type == "Resection (Total)":
        return _join_specimen_parts(organ_name, descriptor, "total resection specimen")
    if specimen_type == "Resection":
        return _join_specimen_parts(organ_name, descriptor, "resection specimen")
    if specimen_type == "Excision":
        return _join_specimen_parts(organ_name, descriptor, "excision specimen")
    if specimen_type == "Biopsy":
        return _join_specimen_parts(organ_name, descriptor, "biopsy specimen")

    title_without_prefix = re.sub(
        r"^protocol for the examination of\s+",
        "",
        cleaned_title,
        flags=re.IGNORECASE,
    )
    title_without_prefix = re.sub(
        r"\bof the\s+" + re.escape(organ_name) + r"\b",
        "",
        title_without_prefix,
        flags=re.IGNORECASE,
    )
    title_without_prefix = clean_whitespace(title_without_prefix)

    words = [
        word for word in re.split(r"\s+", title_without_prefix)
        if word.lower().strip(",()") not in STOPWORDS_IN_SPECIMEN_NAME
    ]
    simplified = clean_whitespace(" ".join(words))
    if simplified and organ_name.lower() not in simplified.lower():
        return f"{simplified} of {organ_name.lower()}"
    if simplified:
        return simplified
    return f"{organ_name} specimen"


def extract_protocol_descriptor(
    raw_title: str,
    organ_name: str,
    specimen_type: str,
    source_stem: str = "",
) -> str:
    candidates = [clean_whitespace(raw_title), clean_whitespace(source_stem.replace("_", " "))]
    filler_patterns = [
        r"^protocol for the examination of\s+",
        r"^specimens? from patients with\s+",
        r"^patients with\s+",
    ]
    type_patterns = [
        r"\bresection specimens?\b",
        r"\bresection\b",
        r"\bbiopsy\b",
        r"\bexcision\b",
        r"\bfine needle aspiration\b",
        r"\bneedle biopsy\b",
        r"\bpunch biopsy\b",
        r"\bwide local excision\b",
        r"\bwide excision\b",
        r"\btotal\b",
    ]
    stop_tokens = {
        organ_name.lower(),
        "breast",
        "organ",
        "specimen",
        "specimens",
        "of",
        "the",
        "from",
        "patients",
        "patient",
        "with",
        "and",
        "for",
        "protocol",
        "examination",
    }

    for candidate in candidates:
        if not candidate:
            continue
        value = candidate.lower()
        for pattern in filler_patterns:
            value = re.sub(pattern, "", value, flags=re.IGNORECASE)
        value = re.sub(re.escape(organ_name.lower()), "", value, flags=re.IGNORECASE)
        for pattern in type_patterns:
            value = re.sub(pattern, "", value, flags=re.IGNORECASE)
        value = re.sub(
            r"ductal carcinoma in situ\s+dcis|dcis\s+ductal carcinoma in situ",
            "dcis",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"ductal carcinoma in situ",
            "dcis",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"[^a-z0-9]+", " ", value)
        words = [word for word in value.split() if word not in stop_tokens]
        deduped_words = []
        for word in words:
            if not deduped_words or deduped_words[-1] != word:
                deduped_words.append(word)
        descriptor = " ".join(deduped_words).strip()
        if descriptor:
            return descriptor.upper() if descriptor == "dcis" else descriptor.title()
    return ""


def _join_specimen_parts(organ_name: str, descriptor: str, suffix: str) -> str:
    parts = [organ_name]
    if descriptor:
        parts.append(descriptor)
    parts.append(suffix)
    return clean_whitespace(" ".join(parts))


def clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()
