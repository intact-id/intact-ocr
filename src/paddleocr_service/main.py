from __future__ import annotations

import asyncio

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from .concurrency import RequestGate
from .config import settings
from .extractor import extract_document
from .models import ExtractedDocument
from .security import verify_api_credentials
from .service import PaddleOcrService

app = FastAPI(title="PaddleOCR Service", version="0.3.0")
service = PaddleOcrService(use_angle_cls=settings.use_angle_cls, lang=settings.ocr_lang)
gate = RequestGate(max_concurrent=settings.max_concurrent_ocr, max_queued=settings.max_queued_ocr)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ocr", dependencies=[Depends(verify_api_credentials)])
async def ocr(file: UploadFile = File(...)) -> dict:
    """Raw OCR extraction — returns all text lines with confidence scores and bounding boxes."""
    _validate_image(file)
    payload = await _read_limited(file)
    async with gate:
        return await _run_ocr(payload)


@app.post("/ocr/extract", dependencies=[Depends(verify_api_credentials)])
async def ocr_extract(file: UploadFile = File(...)) -> ExtractedDocument:
    """
    OCR + structured field extraction.

    Classifies the uploaded document (national_id, passport, drivers_license, alien_card)
    and returns parsed fields: full_name, id_number, date_of_birth, sex, expiry_date, etc.
    """
    _validate_image(file)
    payload = await _read_limited(file)
    async with gate:
        raw = await _run_ocr(payload)
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


async def _read_limited(file: UploadFile) -> bytes:
    """
    Reads the upload in chunks and aborts as soon as it exceeds the size
    cap, instead of buffering the whole body first. file.size (checked in
    _validate_image) isn't always present — e.g. chunked transfer-encoding
    uploads — so this is the real enforcement point.
    """
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File exceeds maximum size of {settings.max_file_size_mb}MB",
            )
        chunks.append(chunk)

    if not total:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    return b"".join(chunks)


async def _run_ocr(payload: bytes) -> dict:
    try:
        return await asyncio.wait_for(
            service.extract_from_bytes_async(payload), timeout=settings.ocr_timeout_seconds
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="OCR processing timed out")
