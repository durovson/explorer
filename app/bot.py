from aiogram import Dispatcher
from aiogram.fsm.storage.base import BaseStorage

from app.config import Settings
from app.handlers import create_router
from app.middleware import CurrentUserMiddleware
from app.repositories import Repositories
from app.services import Services


def create_dispatcher(
    settings: Settings,
    storage: BaseStorage,
    repositories: Repositories,
    services: Services,
) -> Dispatcher:
    dispatcher = Dispatcher(storage=storage)
    dispatcher.update.outer_middleware(CurrentUserMiddleware(services.users))
    dispatcher["settings"] = settings
    dispatcher["referrals"] = services.referrals
    dispatcher["orders"] = services.orders
    dispatcher["pricing"] = services.orders.pricing
    dispatcher["fragment"] = services.fragment
    dispatcher["marketapp"] = services.marketapp
    dispatcher["admin"] = services.admin
    dispatcher["order_repository"] = repositories.orders
    dispatcher.include_router(create_router())
    return dispatcher
