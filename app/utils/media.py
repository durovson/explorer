from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaPhoto,
    Message,
)

ASSETS = Path(__file__).resolve().parent.parent / "assets"
MEDIA = ASSETS / "media"
FALLBACK = ASSETS / "menu.png"
EXTENSIONS = (".gif", ".mp4", ".png", ".jpg", ".jpeg")


def media_path(screen: str) -> Path:
    for extension in EXTENSIONS:
        candidate = MEDIA / f"{screen}{extension}"
        if candidate.is_file():
            return candidate
    return FALLBACK


def input_media(screen: str, caption: str):
    path = media_path(screen)
    source = FSInputFile(path)
    if path.suffix.lower() in {".gif", ".mp4"}:
        return InputMediaAnimation(media=source, caption=caption)
    return InputMediaPhoto(media=source, caption=caption)


async def send_card(
    message: Message,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
    screen: str,
) -> Message:
    path = media_path(screen)
    if path.suffix.lower() in {".gif", ".mp4"}:
        return await message.answer_animation(
            FSInputFile(path), caption=caption, reply_markup=keyboard
        )
    return await message.answer_photo(
        FSInputFile(path), caption=caption, reply_markup=keyboard
    )


async def render_card(
    message: Message,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
    screen: str,
) -> Message:
    if (
        message.from_user
        and message.from_user.is_bot
        and (message.photo or message.animation)
    ):
        try:
            result = await message.edit_media(
                input_media(screen, caption), reply_markup=keyboard
            )
            return result if isinstance(result, Message) else message
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return message
    return await send_card(message, caption, keyboard, screen)


async def edit_card(
    bot: Bot,
    chat_id: int,
    message_id: int,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
    screen: str,
) -> None:
    try:
        await bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=input_media(screen, caption),
            reply_markup=keyboard,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            reply_markup=keyboard,
        )
