from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parent.parent
OFFICIAL_USDT_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = Field(
        default=8000,
        validation_alias=AliasChoices("PORT", "APP_PORT"),
        ge=1,
        le=65535,
    )
    APP_BASE_URL: str = ""
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_BOT_USERNAME: str = ""
    TELEGRAM_USE_POLLING: bool = True
    TELEGRAM_WEBHOOK_PATH: str = "/telegram/webhook"
    TELEGRAM_WEBHOOK_SECRET: str = ""
    REDIS_URL: str = ""
    ADMIN_IDS: str = ""
    SUPPORT_URL: str = "https://t.me/telegram"

    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str

    TON_RECEIVER_ADDRESS: str
    TONCENTER_API_KEY: str = ""
    TONCENTER_V2_URL: str = "https://toncenter.com/api/v2"
    TONCENTER_V3_URL: str = "https://toncenter.com/api/v3"
    USDT_MASTER_ADDRESS: str = OFFICIAL_USDT_MASTER
    PAYMENT_TTL_MINUTES: int = Field(default=15, ge=5, le=60)
    WORKER_INTERVAL_SECONDS: int = Field(default=10, ge=3, le=300)
    PAYMENT_SCAN_LIMIT: int = Field(default=100, ge=10, le=1000)
    PAYMENT_MAX_PAGES: int = Field(default=10, ge=1, le=100)
    ORDER_BATCH_SIZE: int = Field(default=100, ge=1, le=500)

    # Legacy provider. Existing FRAGMENT orders can still be completed after migration.
    FRAGMENT_BASE_URL: str = "https://api.fragment-api.com/v1"
    FRAGMENT_JWT_TOKEN: str = ""
    FRAGMENT_TIMEOUT_SECONDS: int = Field(default=45, ge=10, le=120)

    # Marketapp is the provider for all newly-created orders.
    # Authorization uses the raw token value; never add a Bearer/JWT prefix.
    MARKETAPP_BASE_URL: str = "https://api.marketapp.org"
    MARKETAPP_API_TOKEN: str = ""
    MARKETAPP_WALLET_SEED: str = ""
    MARKETAPP_WALLET_VERSION: str = "V5R1"
    MARKETAPP_TON_API_KEY: str = ""
    MARKETAPP_TIMEOUT_SECONDS: int = Field(default=45, ge=10, le=120)
    MARKETAPP_RENT_PAGE_SIZE: int = Field(default=6, ge=1, le=20)
    MARKETAPP_GRAM_MARKUP: Decimal = Field(default=Decimal("1.03"), ge=Decimal("1"), le=Decimal("2"))
    MARKETAPP_RENT_MARKUP: Decimal = Field(default=Decimal("1.03"), ge=Decimal("1"), le=Decimal("2"))
    MARKETAPP_GRAM_MIN: Decimal = Field(default=Decimal("0.1"), gt=Decimal("0"))
    MARKETAPP_GRAM_MAX: Decimal = Field(default=Decimal("1000"), gt=Decimal("0"))

    FULFILLMENT_LEASE_SECONDS: int = Field(default=180, ge=60, le=900)

    STARS_TON_PER_UNIT: Decimal = Decimal("0.0097")
    STARS_USDT_PER_UNIT: Decimal = Decimal("0.015")
    PREMIUM_3_TON: Decimal = Decimal("4.99")
    PREMIUM_6_TON: Decimal = Decimal("8.99")
    PREMIUM_12_TON: Decimal = Decimal("15.99")
    PREMIUM_3_USDT: Decimal = Decimal("13.99")
    PREMIUM_6_USDT: Decimal = Decimal("24.99")
    PREMIUM_12_USDT: Decimal = Decimal("44.99")

    @property
    def admin_ids(self) -> frozenset[int]:
        return frozenset(
            int(item.strip()) for item in self.ADMIN_IDS.split(",") if item.strip()
        )

    @property
    def marketapp_auto_pay_configured(self) -> bool:
        return bool(self.MARKETAPP_API_TOKEN and self.MARKETAPP_WALLET_SEED)

    @property
    def marketapp_ton_api_key(self) -> str:
        return self.MARKETAPP_TON_API_KEY or self.TONCENTER_API_KEY

    @field_validator("USDT_MASTER_ADDRESS")
    @classmethod
    def official_usdt_only(cls, value: str) -> str:
        value = value.strip()
        if value != OFFICIAL_USDT_MASTER:
            raise ValueError("Only the official USDT-on-TON master is allowed")
        return value

    @field_validator(
        "TELEGRAM_BOT_TOKEN",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "TON_RECEIVER_ADDRESS",
        mode="before",
    )
    @classmethod
    def required_text(cls, value: object) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator(
        "FRAGMENT_JWT_TOKEN",
        "MARKETAPP_API_TOKEN",
        "MARKETAPP_WALLET_SEED",
        "MARKETAPP_TON_API_KEY",
        mode="before",
    )
    @classmethod
    def optional_secret_text(cls, value: object) -> object:
        if value is None:
            return ""
        return value.strip() if isinstance(value, str) else value

    @field_validator("MARKETAPP_WALLET_VERSION")
    @classmethod
    def supported_wallet_version(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"V5R1", "V4R2"}:
            raise ValueError("MARKETAPP_WALLET_VERSION must be V5R1 or V4R2")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
