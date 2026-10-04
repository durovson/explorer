from aiogram import Router

from app.handlers import admin, menu, purchase, rent


def create_router() -> Router:
    router = Router(name="root")
    router.include_routers(menu.router, purchase.router, rent.router, admin.router)
    return router
