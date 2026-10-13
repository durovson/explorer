from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class RenderKeepAlive:
    """Keep a Render web service warm with lightweight self-requests."""

    def __init__(self, settings: Settings):
        self._base_url = settings.APP_BASE_URL.rstrip("/")
        self._enabled = settings.RENDER_KEEPALIVE_ENABLED and bool(self._base_url)
        self._interval = settings.RENDER_KEEPALIVE_INTERVAL_SECONDS
        self._timeout = settings.RENDER_KEEPALIVE_TIMEOUT_SECONDS
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._client: httpx.AsyncClient | None = None

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if not self._enabled or self.is_running:
            return
        self._stop.clear()
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=True,
            headers={"User-Agent": "STRS-TG-Render-KeepAlive/1.0"},
        )
        self._task = asyncio.create_task(self._run(), name="render-keepalive")
        logger.info(
            "Render keep-alive started: interval=%ss endpoint=%s/livez",
            self._interval,
            self._base_url,
        )

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        client = self._client
        self._client = None
        if client is not None:
            await client.aclose()

    async def _run(self) -> None:
        # Do not self-request while the ASGI lifespan is still starting.
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                return
            except TimeoutError:
                pass
            try:
                client = self._client
                if client is None:
                    return
                response = await client.get(f"{self._base_url}/livez")
                response.raise_for_status()
                logger.debug("Render keep-alive ping succeeded: %s", response.status_code)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Render keep-alive ping failed: %s", type(exc).__name__
                )
