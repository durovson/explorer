from html import escape
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.keyboards.menu import back_home
from app.services.admin import AdminService
from app.services.referrals import ReferralService
from app.utils.emoji import premium
from app.utils.media import render_card

router = Router(name="admin")

@router.message(Command("ref_queue", "ref_status", "ref_profile"))
async def referral_admin(message: Message, command: CommandObject, admin: AdminService, referrals: ReferralService) -> None:
    try:
        admin.require(message.from_user.id)
    except PermissionError:
        return
    try:
        args=(command.args or "").split()
        if command.command=="ref_queue":
            rows=await referrals.withdrawals()
            text="\n".join(f"#{w['id']} user={w['user_id']} {w['amount']} {w['currency']} · {w['status']} · {w['wallet_address']}" for w in rows)
            await message.answer(escape(text)[:4000] or "Нет заявок")
            return
        if command.command=="ref_status":
            await referrals.advance(int(args[0]),args[1],args[2] if len(args)>2 else None)
        elif command.command=="ref_profile":
            await referrals.set_profile(int(args[0]),args[1],int(args[2]) if len(args)>2 else None)
        await message.answer("Реферальные данные обновлены.")
    except Exception:
        await message.answer("Операция не выполнена. Проверьте аргументы, статус и hash транзакции.")


def _stats_text(stats) -> str:
    return (
        f"<b>{premium('settings')} Статистика</b>\n\n"
        f"Пользователи: <b>{stats.users}</b>\n"
        f"Заказы: <b>{stats.orders}</b>\n"
        f"Ожидают оплату: <b>{stats.waiting}</b>\n"
        f"Выполнено: <b>{stats.completed}</b>\n"
        f"Ручная проверка: <b>{stats.manual_review}</b>\n\n"
        f"Оборот: <b>{stats.volume_ton} TON</b> / <b>{stats.volume_usdt} USDT</b>"
    )


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery, admin: AdminService) -> None:
    try:
        stats = await admin.stats(callback.from_user.id)
    except PermissionError:
        await callback.answer("Нет доступа", show_alert=True)
        return
    if callback.message:
        await render_card(callback.message, _stats_text(stats), back_home(), "settings")
    await callback.answer()


@router.message(Command("admin_stats"))
async def admin_stats_command(message: Message, admin: AdminService) -> None:
    try:
        stats = await admin.stats(message.from_user.id)
    except PermissionError:
        return
    await message.answer(_stats_text(stats))


@router.message(Command("approve_retry"))
async def approve_retry(
    message: Message, command: CommandObject, admin: AdminService
) -> None:
    try:
        raw_id, reason = (command.args or "").strip().split(maxsplit=1)
        order = await admin.approve_retry(message.from_user.id, UUID(raw_id), reason)
    except PermissionError:
        return
    except Exception as exc:
        await message.answer(f"{premium('cancel')} {escape(str(exc))}")
        return
    await message.answer(
        f"{premium('success')} Заказ <code>{order.id}</code> возвращён в очередь после ручной проверки."
    )
