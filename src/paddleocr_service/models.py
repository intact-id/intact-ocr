from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class DocumentFields(BaseModel):
    full_name: Optional[str] = None
    surname: Optional[str] = None
    given_names: Optional[str] = None
    id_number: Optional[str] = None
    date_of_birth: Optional[str] = None      # ISO YYYY-MM-DD
    sex: Optional[str] = None                # "M" or "F"
    nationality: Optional[str] = None
    expiry_date: Optional[str] = None        # ISO YYYY-MM-DD
    date_of_issue: Optional[str] = None      # ISO YYYY-MM-DD
    place_of_birth: Optional[str] = None
    district_of_birth: Optional[str] = None
    place_of_issue: Optional[str] = None


class FieldConfidence(BaseModel):
    full_name: Optional[float] = None
    surname: Optional[float] = None
    given_names: Optional[float] = None
    id_number: Optional[float] = None
    date_of_birth: Optional[float] = None
    sex: Optional[float] = None
    nationality: Optional[float] = None
    expiry_date: Optional[float] = None
    date_of_issue: Optional[float] = None
    place_of_birth: Optional[float] = None
    district_of_birth: Optional[float] = None
    place_of_issue: Optional[float] = None


class ExtractedDocument(BaseModel):
    document_type: str               # national_id | passport | drivers_license | alien_card | unknown
    document_type_confidence: float
    country_iso3: Optional[str] = None   # ISO-3166-1 alpha-3 detected from OCR (e.g. "KEN", "COD")
    fields: DocumentFields
    field_confidence: FieldConfidence
    overall_confidence: float
    raw_text: str
    line_count: int
    lines: list[dict]
