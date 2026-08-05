from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_key: str = "test_ocr_key"
    api_secret: str = "test_ocr_secret"
    max_file_size_mb: int = 10
    ocr_lang: str = "en"
    use_angle_cls: bool = True

    # Bounds how many requests may be decoding/awaiting OCR at once (per worker
    # process) so a burst of uploads can't buffer unbounded images in memory.
    max_concurrent_ocr: int = 4
    # Requests beyond max_concurrent_ocr queue up to this depth before getting
    # a 503 instead of piling up indefinitely.
    max_queued_ocr: int = 8
    # Hard ceiling on a single OCR call so a pathological image can't hold a
    # slot (and the underlying model lock) forever.
    ocr_timeout_seconds: float = 30.0


settings = Settings()
