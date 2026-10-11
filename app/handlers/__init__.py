from aiogram import Router

from app.handlers import admin, menu, purchase


def create_router() -> Router:
    router = Router(name="root")
    router.include_routers(menu.router, purchase.router, admin.router)
    return router
