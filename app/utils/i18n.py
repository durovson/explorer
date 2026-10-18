from __future__ import annotations

from contextvars import ContextVar, Token

_LANGUAGE: ContextVar[str] = ContextVar("language", default="ru")


def language() -> str:
    return _LANGUAGE.get()


def select_language(value: str) -> Token:
    return _LANGUAGE.set("en" if value == "en" else "ru")


def restore_language(token: Token) -> None:
    _LANGUAGE.reset(token)


def tr(ru: str, en: str) -> str:
    return en if _LANGUAGE.get() == "en" else ru
