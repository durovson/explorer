from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from app.api.keepalive import RenderKeepAlive
from app.api.notifier import OrderNotifier
from app.bot import create_dispatcher
from app.config import Settings
from app.database import SupabaseDatabase
from app.repositories import Repositories
from app.services import (
    AdminService,
    FragmentService,
    OrderService,
    PaymentService,
    ReferralService,
    Services,
    UserService,
)
from app.services.pricing import PriceService
from app.services.settlement import SettlementService
from app.tasks import WorkerManager


@dataclass(slots=True)
class Container:
    settings: Settings
    bot: Bot
    dispatcher: Dispatcher
    storage: BaseStorage
    database: SupabaseDatabase
    repositories: Repositories
    services: Services
    workers: WorkerManager
    keepalive: RenderKeepAlive

    async def close(self) -> None:
        await self.workers.stop()
        await self.keepalive.stop()
        await self.services.payments.close()
        await self.services.fragment.close()
        await self.storage.close()
        await self.bot.session.close()
        await self.database.close()


async def build_container(settings: Settings) -> Container:
    database = SupabaseDatabase(settings)
    await database.connect()
    repositories = Repositories.build(database)
    bot = Bot(
        settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML, link_preview_is_disabled=True
        ),
    )
    storage: BaseStorage = (
        RedisStorage.from_url(settings.REDIS_URL)
        if settings.REDIS_URL
        else MemoryStorage()
    )
    users = UserService(repositories.users)
    pricing = PriceService(settings)
    orders = OrderService(settings, repositories.orders, pricing)
    payments = PaymentService(settings)
    fragment = FragmentService(settings)
    settlement = SettlementService(settings)
    referrals = ReferralService(repositories.users)
    admin = AdminService(settings, repositories.admin, repositories.orders)
    services = Services(users, orders, payments, fragment, referrals, admin)
    dispatcher = create_dispatcher(settings, storage, repositories, services)
    workers = WorkerManager(
        settings,
        repositories.orders,
        repositories.payments,
        payments,
        fragment,
        settlement,
        OrderNotifier(bot, settings),
    )
    keepalive = RenderKeepAlive(settings)
    return Container(
        settings,
        bot,
        dispatcher,
        storage,
        database,
        repositories,
        services,
        workers,
        keepalive,
    )
