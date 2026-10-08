"""
src/core/config.py
Загрузка и валидация настроек из .env через pydantic.
"""

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Корень проекта (на 2 уровня выше src/core/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Все настройки проекта. Читаются из .env."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Общие ---
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = Field(default="")
    TELEGRAM_CHAT_ID: str = Field(default="")

    # --- Прокси (общий, устаревший) ---
    PROXY_URL: Optional[str] = Field(default=None)

    # --- Прокси для кошельков (по одному на кошелёк) ---
    PROXY_FARM_01: Optional[str] = Field(default=None)
    PROXY_FARM_02: Optional[str] = Field(default=None)
    PROXY_FARM_03: Optional[str] = Field(default=None)

    # --- RPC ---
    POLYGON_RPC_URL: str = Field(default="https://polygon-rpc.com")

    # --- Капча ---
    CAPTCHA_API_KEY: Optional[str] = Field(default=None)

    # --- 1inch API ---
    ONEINCH_API_KEY: Optional[str] = Field(default=None)

    # --- БД ---
    DATABASE_URL: str = Field(default="sqlite:///./data/airdrop.db")

    # --- Шифрование кошельков ---
    WALLET_ENCRYPTION_KEY: str = Field(default="")
    COLD_WALLET_ADDRESS: str = Field(default="")

    # --- Валидация ---
    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"LOG_LEVEL должен быть одним из: {allowed}")
        return v_upper

    @field_validator("POLYGON_RPC_URL")
    @classmethod
    def validate_rpc(cls, v: str) -> str:
        if not v.startswith("http"):
            raise ValueError("POLYGON_RPC_URL должен начинаться с http:// или https://")
        return v

    @field_validator("WALLET_ENCRYPTION_KEY")
    @classmethod
    def validate_encryption_key(cls, v: str) -> str:
        if v and len(v) < 32:
            raise ValueError(
                "WALLET_ENCRYPTION_KEY должен быть не короче 32 символов. "
                "Сгенерируй: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        return v


# Глобальный объект настроек — импортируется во всех модулях
settings = Settings()
