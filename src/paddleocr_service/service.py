from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image
from paddleocr import PaddleOCR


@dataclass
class OcrLine:
    text: str
    confidence: float
    box: list[list[float]]


class PaddleOcrService:
    def __init__(self, *, use_angle_cls: bool = True, lang: str = "en") -> None:
        self._ocr = PaddleOCR(use_angle_cls=use_angle_cls, lang=lang)

    def extract_from_bytes(self, payload: bytes) -> dict[str, Any]:
        """Synchronous OCR — CPU-bound, blocks the calling thread."""
        image = Image.open(io.BytesIO(payload)).convert("RGB")
        image_array = np.array(image)
        result = self._ocr.ocr(image_array, cls=True)
        lines = self._normalize(result)

        return {
            "line_count": len(lines),
            "text": "\n".join(line.text for line in lines),
            "lines": [
                {
                    "text": line.text,
                    "confidence": line.confidence,
                    "box": line.box,
                }
                for line in lines
            ],
        }

    async def extract_from_bytes_async(self, payload: bytes) -> dict[str, Any]:
        """
        Async wrapper — offloads the CPU-bound OCR to a thread pool so
        FastAPI's event loop stays free for other requests.
        """
        return await asyncio.to_thread(self.extract_from_bytes, payload)

    def _normalize(self, result: list[Any]) -> list[OcrLine]:
        normalized: list[OcrLine] = []

        for page in result or []:
            if not page:
                continue
            for item in page:
                box = item[0]
                text = item[1][0]
                confidence = float(item[1][1])
                normalized.append(
                    OcrLine(text=text, confidence=confidence, box=box)
                )

        return normalized
