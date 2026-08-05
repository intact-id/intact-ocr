from __future__ import annotations

import asyncio

from fastapi import HTTPException


class RequestGate:
    """
    Caps how many requests may hold an OCR slot at once, with a bounded
    waiting queue on top. Requests beyond max_concurrent queue up to
    max_queued deep; anything past that is rejected immediately with a 503
    instead of buffering unbounded uploads in memory.
    """

    def __init__(self, max_concurrent: int, max_queued: int) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_queued = max_queued
        self._waiting = 0
        self._waiting_lock = asyncio.Lock()

    async def __aenter__(self) -> "RequestGate":
        async with self._waiting_lock:
            if self._waiting >= self._max_queued:
                raise HTTPException(
                    status_code=503,
                    detail="Server is at capacity, please retry shortly",
                )
            self._waiting += 1
        try:
            await self._semaphore.acquire()
        finally:
            async with self._waiting_lock:
                self._waiting -= 1
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._semaphore.release()
