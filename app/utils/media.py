from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, Message


def _is_not_modified(exc: TelegramBadRequest) -> bool:
    return "message is not modified" in str(exc).lower()


async def send_card(
    message: Message,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
    screen: str,
) -> Message:
    """Send a text-only bot card.

    `screen` is intentionally kept in the public signature so existing handlers do
    not need per-screen branches, but media assets are no longer used anywhere.
    """
    _ = screen
    return await message.answer(caption, reply_markup=keyboard)


async def render_card(
    message: Message,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
    screen: str,
) -> Message:
    """Render one text-only menu message.

    Legacy photo/animation cards cannot be converted to text with Telegram's edit
    API. On the first interaction after this release we delete that old media
    message and replace it once with a text card. All subsequent navigation edits
    the same text message in place.
    """
    _ = screen
    if message.from_user and message.from_user.is_bot:
        has_media = bool(
            message.photo
            or message.animation
            or message.video
            or message.document
            or message.sticker
        )
        if not has_media:
            try:
                result = await message.edit_text(caption, reply_markup=keyboard)
                return result if isinstance(result, Message) else message
            except TelegramBadRequest as exc:
                if _is_not_modified(exc):
                    return message
            except TelegramRetryAfter:
                return message

        # One-time migration from the old media UI to a text-only card.
        try:
            await message.delete()
        except (TelegramBadRequest, TelegramRetryAfter):
            # Do not create duplicate menus when Telegram refuses deletion.
            try:
                if message.caption is not None:
                    result = await message.edit_caption(
                        caption=caption, reply_markup=keyboard
                    )
                    return result if isinstance(result, Message) else message
            except (TelegramBadRequest, TelegramRetryAfter):
                pass
            return message
        return await message.answer(caption, reply_markup=keyboard)

    return await send_card(message, caption, keyboard, screen)


async def edit_card(
    bot: Bot,
    chat_id: int,
    message_id: int,
    caption: str,
    keyboard: InlineKeyboardMarkup | None,
    screen: str,
) -> Message | None:
    """Edit a stored text card, migrating a legacy media card exactly once.

    The returned Message is important when a legacy media message had to be
    replaced: callers can persist the new message_id and avoid future duplicates.
    """
    _ = screen
    try:
        result = await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=caption,
            reply_markup=keyboard,
        )
        return result if isinstance(result, Message) else None
    except TelegramRetryAfter:
        return None
    except TelegramBadRequest as exc:
        if _is_not_modified(exc):
            return None

    # A legacy media card has no editable text body. Remove it and create one
    # text card, then let the caller store the replacement message id.
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except (TelegramBadRequest, TelegramRetryAfter):
        return None
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=keyboard,
        )
    except TelegramRetryAfter:
        return None
