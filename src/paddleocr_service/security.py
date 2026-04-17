from __future__ import annotations

from fastapi import Header, HTTPException
from .config import settings


async def verify_api_credentials(
    x_api_key: str | None = Header(default=None),
    x_api_secret: str | None = Header(default=None),
) -> None:
    if not x_api_key or not x_api_secret:
        raise HTTPException(status_code=401, detail="Missing X-API-Key or X-API-Secret header")
    if x_api_key != settings.api_key or x_api_secret != settings.api_secret:
        raise HTTPException(status_code=401, detail="Invalid API credentials")
