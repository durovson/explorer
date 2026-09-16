from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request

from app.config import Settings
from app.loader import Container, build_container

logger = logging.getLogger(__name__)


def create_application(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = await build_container(settings)
        app.state.container = container
        await container.database.ping()
        await container.workers.start()
        polling_task: asyncio.Task[None] | None = None
        if settings.TELEGRAM_USE_POLLING:
            await container.bot.delete_webhook(drop_pending_updates=False)
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
                drop_pending_updates=False,
            )
        try:
            yield
        finally:
            if polling_task:
                polling_task.cancel()
                with suppress(asyncio.CancelledError):
                    await polling_task
            await container.close()

    app = FastAPI(title="Stars & Premium Shop", lifespan=lifespan)

    @app.get("/health")
    async def health(request: Request) -> dict[str, object]:
        container: Container = request.app.state.container
        database_ok = await container.database.ping()
        return {
            "ok": database_ok and container.workers.healthy,
            "database": database_ok,
            "workers": container.workers.healthy,
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
        await container.dispatcher.feed_update(container.bot, update)
        return {"ok": True}

    return app
