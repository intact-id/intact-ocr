from __future__ import annotations

from .classifier import classify
from .country_registry import detect_country
from .national_id import NationalIdExtractor
from .passport import PassportExtractor
from .drivers_license import DriversLicenseExtractor
from .residence_permit import ResidencePermitExtractor
from ..models import DocumentFields, FieldConfidence, ExtractedDocument

_EXTRACTORS = {
    "national_id":       NationalIdExtractor(),
    "passport":          PassportExtractor(),
    "drivers_license":   DriversLicenseExtractor(),
    "residence_permit":  ResidencePermitExtractor(),
}


def extract_document(ocr_result: dict) -> ExtractedDocument:
    """
    Given the output of PaddleOcrService.extract_from_bytes(), classify the
    document type and extract structured fields.

    Country detection runs first (via MRZ or keyword scoring against
    documents.yaml) so extractors can use country-specific label vocabularies.
    """
    lines_data: list[dict] = ocr_result.get("lines", [])
    texts = [l["text"] for l in lines_data]
    line_conf: dict[str, float] = {l["text"]: l["confidence"] for l in lines_data}

    # Detect country before classification — both use the same texts
    country_iso3 = detect_country(texts)

    doc_type, type_conf = classify(texts)

    extractor = _EXTRACTORS.get(doc_type)
    if extractor is None and country_iso3:
        # Country detected but document type unknown — try national_id as best-effort fallback.
        # Partial extraction is better than returning zero fields.
        extractor = _EXTRACTORS["national_id"]
    if extractor is not None:
        fields, field_conf = extractor.extract(texts, line_conf, country=country_iso3)
    else:
        fields = DocumentFields()
        field_conf = FieldConfidence()

    populated = [v for v in field_conf.model_dump().values() if v is not None]
    overall = round(sum(populated) / len(populated), 3) if populated else 0.0

    return ExtractedDocument(
        document_type=doc_type,
        document_type_confidence=type_conf,
        country_iso3=country_iso3,
        fields=fields,
        field_confidence=field_conf,
        overall_confidence=overall,
        raw_text=ocr_result.get("text", ""),
        line_count=ocr_result.get("line_count", 0),
        lines=lines_data,
    )
