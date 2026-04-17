from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_key: str = "test_ocr_key"
    api_secret: str = "test_ocr_secret"
    max_file_size_mb: int = 10
    ocr_lang: str = "en"
    use_angle_cls: bool = True


settings = Settings()
