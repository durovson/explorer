from aiogram import Dispatcher
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import SimpleEventIsolation

from app.config import Settings
from app.handlers import create_router
from app.middleware import CurrentUserMiddleware, FastCallbackMiddleware
from app.repositories import Repositories
from app.services import Services


def create_dispatcher(
    settings: Settings,
    storage: BaseStorage,
    repositories: Repositories,
    services: Services,
) -> Dispatcher:
    # Fast callback ACK happens before any database/user lookup. Event isolation
    # then prevents two rapid taps from racing FSM/menu state against each other.
    dispatcher = Dispatcher(storage=storage, events_isolation=SimpleEventIsolation())
    dispatcher.update.outer_middleware(FastCallbackMiddleware())
    dispatcher.update.middleware(CurrentUserMiddleware(services.users))
    dispatcher["settings"] = settings
    dispatcher["referrals"] = services.referrals
    dispatcher["orders"] = services.orders
    dispatcher["pricing"] = services.orders.pricing
    dispatcher["fragment"] = services.fragment
    dispatcher["admin"] = services.admin
    dispatcher["order_repository"] = repositories.orders
    dispatcher.include_router(create_router())
    return dispatcher
