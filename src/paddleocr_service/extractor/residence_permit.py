from __future__ import annotations

from typing import Optional

from .national_id import NationalIdExtractor
from ..models import DocumentFields, FieldConfidence


class ResidencePermitExtractor:
    """
    Residence permit / alien registration card.
    Same extraction logic as a national ID — delegates entirely.
    The document_type in the response distinguishes it.
    """

    def extract(
        self,
        texts: list[str],
        line_conf: dict[str, float],
        country: Optional[str] = None,
    ) -> tuple[DocumentFields, FieldConfidence]:
        return NationalIdExtractor().extract(texts, line_conf, country=country)

