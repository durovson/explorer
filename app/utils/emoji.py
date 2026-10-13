from __future__ import annotations

# Verified Telegram custom-emoji IDs from public Telegram UI icon packs.
# InlineKeyboardButton.icon_custom_emoji_id renders these as Premium-style icons.
BACK = "5877536313623711363"
HOME = "5807868868886009920"
SUCCESS = "5920052658743283381"
CANCEL = "5258226313285607065"
SETTINGS = "5258420634785947640"
DIAMOND = "5807465992363710697"
STAR = "5874948844935974490"
WARNING = "5258474669769497337"
EDIT = "5839380464116175529"
USER = "5258362837411045098"
USERS = "5258513401784573443"
PAYMENT = "5258260149037965799"
COIN = "5258368777350816286"
SPARKLES = "5877318502947229960"
ROBOT = "5258093637450866522"
CALENDAR = "5258105663359294787"
DOCUMENT = "5258477770735885832"
HELP = "5258503720928288433"
LOCK = "5258476306152038031"

_EMOJI = {
    "back": (BACK, "⬅️"),
    "home": (HOME, "🏠"),
    "success": (SUCCESS, "✅"),
    "cancel": (CANCEL, "❌"),
    "settings": (SETTINGS, "⚙️"),
    "diamond": (DIAMOND, "💎"),
    "star": (STAR, "⭐️"),
    "warning": (WARNING, "⚠️"),
    "edit": (EDIT, "✏️"),
    "user": (USER, "👤"),
    "users": (USERS, "👥"),
    "payment": (PAYMENT, "💳"),
    "coin": (COIN, "🪙"),
    "sparkles": (SPARKLES, "✨"),
    "robot": (ROBOT, "🤖"),
    "calendar": (CALENDAR, "🗓"),
    "document": (DOCUMENT, "📄"),
    "help": (HELP, "❓"),
    "lock": (LOCK, "🔒"),
}


def premium(name: str) -> str:
    emoji_id, fallback = _EMOJI[name]
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
