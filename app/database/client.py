from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.config import Settings
from supabase import AsyncClient, AsyncClientOptions, acreate_client

T = TypeVar("T")


class SupabaseDatabase:
    """Small async/concurrency boundary around Supabase PostgREST."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._capacity = asyncio.Semaphore(12)
        self.client: AsyncClient | None = None

    async def connect(self) -> None:
        self.client = await acreate_client(
            self._settings.SUPABASE_URL,
            self._settings.SUPABASE_SERVICE_ROLE_KEY,
            options=AsyncClientOptions(auto_refresh_token=False, persist_session=False),
        )

    def require_client(self) -> AsyncClient:
        if self.client is None:
            raise RuntimeError("Supabase is not connected")
        return self.client

    async def run(self, operation: Callable[[AsyncClient], Awaitable[T]]) -> T:
        async with self._capacity:
            async with asyncio.timeout(30):
                return await operation(self.require_client())

    async def rpc(self, name: str, params: dict[str, object]):
        return await self.run(lambda client: client.rpc(name, params).execute())

    async def ping(self) -> bool:
        response = await self.run(
            lambda client: client.table("bot_settings").select("id").limit(1).execute()
        )
        return response.data is not None

    async def close(self) -> None:
        if self.client is not None:
            await self.client.auth.close()
            await self.client.postgrest.aclose()
            self.client = None
