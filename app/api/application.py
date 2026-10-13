from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from contextlib import asynccontextmanager, suppress
from time import monotonic

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request

from app.config import Settings
from app.loader import Container, build_container

logger = logging.getLogger(__name__)

_RECENT_UPDATE_TTL_SECONDS = 180.0
_RECENT_UPDATE_MAX = 4_096


class _RecentUpdateIds:
    """Small in-memory guard against Telegram webhook retries."""

    def __init__(self) -> None:
        self._items: OrderedDict[int, float] = OrderedDict()

    def accept(self, update_id: int) -> bool:
        now = monotonic()
        while self._items:
            first_id, seen_at = next(iter(self._items.items()))
            if now - seen_at < _RECENT_UPDATE_TTL_SECONDS:
                break
            self._items.pop(first_id, None)
        if update_id in self._items:
            self._items.move_to_end(update_id)
            return False
        self._items[update_id] = now
        self._items.move_to_end(update_id)
        while len(self._items) > _RECENT_UPDATE_MAX:
            self._items.popitem(last=False)
        return True


def create_application(settings: Settings) -> FastAPI:
    update_tasks: set[asyncio.Task[object]] = set()
    recent_updates = _RecentUpdateIds()

    def _track_update_task(task: asyncio.Task[object]) -> None:
        update_tasks.add(task)

        def finished(done: asyncio.Task[object]) -> None:
            update_tasks.discard(done)
            if done.cancelled():
                return
            try:
                done.result()
            except Exception:
                logger.exception("Telegram update task failed")

        task.add_done_callback(finished)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = await build_container(settings)
        app.state.container = container
        await container.database.ping()
        await container.workers.start()
        polling_task: asyncio.Task[None] | None = None
        if settings.TELEGRAM_USE_POLLING:
            await container.bot.delete_webhook(
                drop_pending_updates=settings.TELEGRAM_DROP_PENDING_UPDATES
            )
            polling_task = asyncio.create_task(
                container.dispatcher.start_polling(
                    container.bot, handle_signals=False, close_bot_session=False
                ),
                name="telegram-polling",
            )
        else:
            webhook_url = (
                f"{settings.APP_BASE_URL.rstrip('/')}{settings.TELEGRAM_WEBHOOK_PATH}"
            )
            await container.bot.set_webhook(
                webhook_url,
                secret_token=settings.TELEGRAM_WEBHOOK_SECRET or None,
                drop_pending_updates=settings.TELEGRAM_DROP_PENDING_UPDATES,
            )
        await container.keepalive.start()
        try:
            yield
        finally:
            for task in tuple(update_tasks):
                task.cancel()
            if update_tasks:
                await asyncio.gather(*tuple(update_tasks), return_exceptions=True)
                update_tasks.clear()
            if polling_task:
                polling_task.cancel()
                with suppress(asyncio.CancelledError):
                    await polling_task
            await container.close()

    app = FastAPI(title="Stars & Premium Shop", lifespan=lifespan)

    @app.get("/livez")
    async def livez() -> dict[str, bool]:
        # Keep-alive endpoint must stay independent from Supabase/provider IO.
        return {"ok": True}

    @app.get("/health")
    async def health(request: Request) -> dict[str, object]:
        container: Container = request.app.state.container
        database_ok = await container.database.ping()
        return {
            "ok": database_ok and container.workers.healthy,
            "database": database_ok,
            "workers": container.workers.healthy,
            "keepalive": container.keepalive.is_running
            if container.keepalive.is_enabled
            else None,
            "last_success": {
                name: value.isoformat()
                for name, value in container.workers.last_success.items()
            },
        }

    @app.post(settings.TELEGRAM_WEBHOOK_PATH)
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, bool]:
        if settings.TELEGRAM_USE_POLLING:
            raise HTTPException(status_code=404)
        if settings.TELEGRAM_WEBHOOK_SECRET and (
            x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET
        ):
            raise HTTPException(status_code=403)
        container: Container = request.app.state.container
        update = Update.model_validate(
            await request.json(), context={"bot": container.bot}
        )
        if not recent_updates.accept(update.update_id):
            return {"ok": True}
        # Return 200 to Telegram immediately. Slow provider/database work then
        # continues in-process, preventing webhook retries from replaying menus.
        task = asyncio.create_task(
            container.dispatcher.feed_update(container.bot, update),
            name=f"telegram-update:{update.update_id}",
        )
        _track_update_task(task)
        return {"ok": True}

    return app
