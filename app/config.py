from __future__ import annotations

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
    APP_BASE_URL: str = Field(
        default="",
        validation_alias=AliasChoices("APP_BASE_URL", "RENDER_EXTERNAL_URL"),
    )
    RENDER_KEEPALIVE_ENABLED: bool = True
    RENDER_KEEPALIVE_INTERVAL_SECONDS: int = Field(default=600, ge=60, le=840)
    RENDER_KEEPALIVE_TIMEOUT_SECONDS: int = Field(default=10, ge=1, le=60)

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_BOT_USERNAME: str = ""
    TELEGRAM_USE_POLLING: bool = False
    TELEGRAM_WEBHOOK_PATH: str = "/telegram/webhook"
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_DROP_PENDING_UPDATES: bool = True
    REDIS_URL: str = ""
    ADMIN_IDS: str = ""
    SUPPORT_URL: str = "https://t.me/telegram"

    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str

    TON_RECEIVER_ADDRESS: str
    SERVICE_PROFIT_ADDRESS: str
    TONCENTER_API_KEY: str
    TONCENTER_V2_URL: str = "https://toncenter.com/api/v2"
    TONCENTER_V3_URL: str = "https://toncenter.com/api/v3"
    TONCENTER_RPS_LIMIT: int = Field(default=10, ge=1, le=10)
    USDT_MASTER_ADDRESS: str = OFFICIAL_USDT_MASTER
    PAYMENT_TTL_MINUTES: int = Field(default=15, ge=5, le=60)
    WORKER_INTERVAL_SECONDS: int = Field(default=10, ge=3, le=300)
    PAYMENT_SCAN_LIMIT: int = Field(default=100, ge=10, le=1000)
    PAYMENT_MAX_PAGES: int = Field(default=10, ge=1, le=100)
    ORDER_BATCH_SIZE: int = Field(default=100, ge=1, le=500)

    MARKETAPP_API_TOKEN: str
    MARKETAPP_WALLET_SEED: str
    MARKETAPP_WALLET_VERSION: str = "V5R1"
    MARKETAPP_API_PROVIDER: str = "toncenter"
    MARKETAPP_TIMEOUT_SECONDS: int = Field(default=45, ge=10, le=120)
    FULFILLMENT_LEASE_SECONDS: int = Field(default=180, ge=60, le=900)

    @property
    def admin_ids(self) -> frozenset[int]:
        return frozenset(
            int(item.strip()) for item in self.ADMIN_IDS.split(",") if item.strip()
        )

    @field_validator("USDT_MASTER_ADDRESS")
    @classmethod
    def official_usdt_only(cls, value: str) -> str:
        value = value.strip()
        if value != OFFICIAL_USDT_MASTER:
            raise ValueError("Only the official USDT-on-TON master is allowed")
        return value

    @field_validator("MARKETAPP_WALLET_VERSION")
    @classmethod
    def supported_wallet_version(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in {"V5R1", "V4R2"}:
            raise ValueError("MARKETAPP_WALLET_VERSION must be V5R1 or V4R2")
        return value

    @field_validator("MARKETAPP_API_PROVIDER")
    @classmethod
    def supported_marketapp_provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"tonapi", "toncenter"}:
            raise ValueError("MARKETAPP_API_PROVIDER must be tonapi or toncenter")
        return value

    @field_validator("MARKETAPP_WALLET_SEED")
    @classmethod
    def wallet_seed_words(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("must be a mnemonic seed phrase")
        value = " ".join(value.split())
        if len(value.split()) not in {12, 18, 24}:
            raise ValueError("MARKETAPP_WALLET_SEED must contain 12, 18 or 24 words")
        return value

    @field_validator(
        "TELEGRAM_BOT_TOKEN",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "TON_RECEIVER_ADDRESS",
        "SERVICE_PROFIT_ADDRESS",
        "TONCENTER_API_KEY",
        "MARKETAPP_API_TOKEN",
        mode="before",
    )
    @classmethod
    def required_text(cls, value: object) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must not be empty")
        return value.strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
