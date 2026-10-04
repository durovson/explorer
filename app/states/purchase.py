from aiogram.fsm.state import State, StatesGroup


class PurchaseStates(StatesGroup):
    recipient = State()
    custom_stars = State()
    custom_gram = State()
