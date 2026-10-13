from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import (
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaPhoto,
    Message,
)

ASSETS = Path(__file__).resolve().parent.parent / "assets"
MEDIA = ASSETS / "media"
FALLBACK = MEDIA / "main_menu.jpg"
EXTENSIONS = (".gif", ".mp4", ".png", ".jpg", ".jpeg")
_MEDIA_FILE_IDS: dict[Path, str] = {}
_MESSAGE_MEDIA_PATHS: dict[tuple[int, int], Path] = {}


def media_path(screen: str) -> Path:
    for extension in EXTENSIONS:
        candidate = MEDIA / f"{screen}{extension}"
        if candidate.is_file():
            return candidate
    return FALLBACK


def _source(path: Path) -> str | FSInputFile:
    return _MEDIA_FILE_IDS.get(path) or FSInputFile(path)


def _input_media(path: Path, caption: str):
    source = _source(path)
    if path.suffix.lower() in {".gif", ".mp4"}:
        return InputMediaAnimation(media=source, caption=caption)
    return InputMediaPhoto(media=source, caption=caption)


def input_media(screen: str, caption: str):
    return _input_media(media_path(screen), caption)


def _message_key(message: Message) -> tuple[int, int]:
    return message.chat.id, message.message_id


def _remember(path: Path, message: Message) -> None:
    if message.animation:
        _MEDIA_FILE_IDS[path] = message.animation.file_id
    elif message.photo:
        _MEDIA_FILE_IDS[path] = message.photo[-1].file_id
    _MESSAGE_MEDIA_PATHS[_message_key(message)] = path


def _same_media(message: Message, path: Path) -> bool:
    return _MESSAGE_MEDIA_PATHS.get(_message_key(message)) == path


def _is_not_modified(exc: TelegramBadRequest) -> bool:
    return "message is not modified" in str(exc).lower()


async def send_card(
    message: Message,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
    screen: str,
) -> Message:
    path = media_path(screen)
    if path.suffix.lower() in {".gif", ".mp4"}:
        result = await message.answer_animation(
            _source(path), caption=caption, reply_markup=keyboard
        )
    else:
        result = await message.answer_photo(
            _source(path), caption=caption, reply_markup=keyboard
        )
    _remember(path, result)
    return result


async def _edit_caption(
    message: Message,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
) -> Message:
    result = await message.edit_caption(caption=caption, reply_markup=keyboard)
    return result if isinstance(result, Message) else message


async def render_card(
    message: Message,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
    screen: str,
) -> Message:
    """Edit the existing bot card; never spam a replacement on callback errors."""
    path = media_path(screen)
    if message.from_user and message.from_user.is_bot:
        if message.photo or message.animation:
            if _same_media(message, path):
                try:
                    return await _edit_caption(message, caption, keyboard)
                except TelegramBadRequest as exc:
                    if _is_not_modified(exc):
                        return message
                except TelegramRetryAfter:
                    return message
            try:
                result = await message.edit_media(
                    media=_input_media(path, caption), reply_markup=keyboard
                )
                if isinstance(result, Message):
                    _remember(path, result)
                    return result
                return message
            except TelegramRetryAfter:
                try:
                    return await _edit_caption(message, caption, keyboard)
                except (TelegramBadRequest, TelegramRetryAfter):
                    return message
            except TelegramBadRequest as exc:
                if _is_not_modified(exc):
                    _MESSAGE_MEDIA_PATHS[_message_key(message)] = path
                    return message
                if path in _MEDIA_FILE_IDS:
                    _MEDIA_FILE_IDS.pop(path, None)
                    try:
                        result = await message.edit_media(
                            media=_input_media(path, caption), reply_markup=keyboard
                        )
                        if isinstance(result, Message):
                            _remember(path, result)
                            return result
                        return message
                    except (TelegramBadRequest, TelegramRetryAfter):
                        pass
                try:
                    return await _edit_caption(message, caption, keyboard)
                except (TelegramBadRequest, TelegramRetryAfter):
                    return message
        try:
            result = await message.edit_text(caption, reply_markup=keyboard)
            return result if isinstance(result, Message) else message
        except TelegramBadRequest as exc:
            if _is_not_modified(exc):
                return message
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
    """Edit a remembered card without creating a second menu message."""
    path = media_path(screen)
    key = (chat_id, message_id)
    if _MESSAGE_MEDIA_PATHS.get(key) == path:
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=caption,
                reply_markup=keyboard,
            )
            return
        except TelegramBadRequest as exc:
            if _is_not_modified(exc):
                return
        except TelegramRetryAfter:
            return
    try:
        result = await bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=_input_media(path, caption),
            reply_markup=keyboard,
        )
        if isinstance(result, Message):
            _remember(path, result)
        else:
            _MESSAGE_MEDIA_PATHS[key] = path
        return
    except TelegramRetryAfter:
        pass
    except TelegramBadRequest as exc:
        if _is_not_modified(exc):
            _MESSAGE_MEDIA_PATHS[key] = path
            return
        if path in _MEDIA_FILE_IDS:
            _MEDIA_FILE_IDS.pop(path, None)
            try:
                result = await bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=message_id,
                    media=_input_media(path, caption),
                    reply_markup=keyboard,
                )
                if isinstance(result, Message):
                    _remember(path, result)
                else:
                    _MESSAGE_MEDIA_PATHS[key] = path
                return
            except (TelegramBadRequest, TelegramRetryAfter):
                pass
    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            reply_markup=keyboard,
        )
    except TelegramBadRequest as exc:
        if not _is_not_modified(exc):
            raise
