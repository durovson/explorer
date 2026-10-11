from enum import StrEnum


class ProductType(StrEnum):
    STARS = "STARS"
    PREMIUM = "PREMIUM"


class Currency(StrEnum):
    TON = "TON"
    USDT = "USDT"


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    WAITING_PAYMENT = "WAITING_PAYMENT"
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


TERMINAL_ORDER_STATUSES = frozenset(
    {OrderStatus.COMPLETED, OrderStatus.EXPIRED, OrderStatus.CANCELLED}
)


class FulfillmentAttemptStatus(StrEnum):
    CLAIMED = "CLAIMED"
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class ReferralRewardStatus(StrEnum):
    RECORDED = "RECORDED"
    PAID = "PAID"
