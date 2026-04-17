from __future__ import annotations

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from .config import settings
from .extractor import extract_document
from .models import ExtractedDocument
from .security import verify_api_credentials
from .service import PaddleOcrService

app = FastAPI(title="PaddleOCR Service", version="0.3.0")
service = PaddleOcrService(use_angle_cls=settings.use_angle_cls, lang=settings.ocr_lang)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ocr", dependencies=[Depends(verify_api_credentials)])
async def ocr(file: UploadFile = File(...)) -> dict:
    """Raw OCR extraction — returns all text lines with confidence scores and bounding boxes."""
    _validate_image(file)
    payload = await file.read()
    _validate_payload(payload)
    return await service.extract_from_bytes_async(payload)


@app.post("/ocr/extract", dependencies=[Depends(verify_api_credentials)])
async def ocr_extract(file: UploadFile = File(...)) -> ExtractedDocument:
    """
    OCR + structured field extraction.

    Classifies the uploaded document (national_id, passport, drivers_license, alien_card)
    and returns parsed fields: full_name, id_number, date_of_birth, sex, expiry_date, etc.
    """
    _validate_image(file)
    payload = await file.read()
    _validate_payload(payload)

    raw = await service.extract_from_bytes_async(payload)
    return extract_document(raw)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_image(file: UploadFile) -> None:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are supported")
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if file.size and file.size > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum size of {settings.max_file_size_mb}MB",
        )


def _validate_payload(payload: bytes) -> None:
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
