from __future__ import annotations

# The same Telegram custom-emoji family used by the GRNT navigation UI.
DOCUMENTS = "6028226658543082010"
DETAILS = "5875206779196935950"
SETTINGS = "5877260593903177342"
REFERRALS = "5942877472163892475"
FAQ = "5985833664884250583"
WALLET = "5769403330761593044"
CREATE_DEAL = "5956561916573782596"
MY_DEALS = "5967548335542767952"
SUPPORT = "5967411695453213733"
LANGUAGE = "5778184941154078090"
BACK = "5877629862306385808"
HOME = "6010362983320916413"
TON = "5778546023349621090"
CONFIRM = "5776375003280838798"
PENDING = "5778605968208170641"
COMPLETE = "5843908536467198016"
MESSAGE = "5985630530111020079"
WARNING = "5881702736843511327"
CANCEL = "5778527486270770928"
MONEY = "5778318458802409852"
ROBOT = "5985780596268339498"
PERSON = "5908808657700655253"
INFO = "5879785854284599288"
ALERT = "5775887550262546277"
BRUSH = "5764779661028495989"
LOCK = "5879895758202735862"
STATS = "5778139491810155937"
PREVIOUS = "5877536313623711363"
NEXT = "5875506366050734240"

# Compatibility names used throughout this bot.
SUCCESS = "5843908536467198016"
DIAMOND = "5280962371207077415"
STAR = "5258165702707125574"
EDIT = BRUSH
USER = PERSON
USERS = REFERRALS
PAYMENT = TON
COIN = MONEY
SPARKLES = STATS
CALENDAR = DETAILS
DOCUMENT = MY_DEALS
HELP = FAQ

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
    "documents": (DOCUMENTS, "📚"),
    "help": (HELP, "❓"),
    "lock": (LOCK, "🔒"),
    "language": (LANGUAGE, "🌐"),
    "info": (INFO, "ℹ️"),
    "pending": (PENDING, "⏳"),
    "message": (MESSAGE, "💬"),
}


def premium(name: str) -> str:
    emoji_id, fallback = _EMOJI[name]
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
