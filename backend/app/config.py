"""Centralized config loaded from environment variables."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve absolute path to backend/.env so the workflow (which runs from the
# workspace root) still picks it up. Real OS env vars always take precedence.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        extra="ignore",
        case_sensitive=False,
    )

    # LLM
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model_reasoning: str = Field(default="llama-3.3-70b-versatile")
    groq_model_nlu: str = Field(default="llama-3.1-8b-instant")

    # DB
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_service_key: str = Field(default="", alias="SUPABASE_SERVICE_KEY")

    # Twilio
    twilio_account_sid: str = Field(default="", alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field(default="", alias="TWILIO_AUTH_TOKEN")
    twilio_whatsapp_from: str = Field(default="", alias="TWILIO_WHATSAPP_FROM")

    # Email
    gmail_user: str = Field(default="", alias="GMAIL_USER")
    gmail_app_password: str = Field(default="", alias="GMAIL_APP_PASSWORD")
    resend_api_key: str = Field(default="", alias="RESEND_API_KEY")
    email_from: str = Field(default="CareLoop Care Team <onboarding@resend.dev>", alias="EMAIL_FROM")

    # Razorpay
    razorpay_key_id: str = Field(default="", alias="RAZORPAY_KEY_ID")
    razorpay_key_secret: str = Field(default="", alias="RAZORPAY_KEY_SECRET")
    razorpay_webhook_secret: str = Field(default="", alias="RAZORPAY_WEBHOOK_SECRET")

    # Demo defaults
    doctor_email: str = Field(default="", alias="DOCTOR_EMAIL")
    doctor_phone: str = Field(default="", alias="DOCTOR_PHONE")
    caregiver_email_default: str = Field(default="", alias="CAREGIVER_EMAIL_DEFAULT")

    # Consultation pricing (per-booking fee charged before doctor is notified).
    # Defaults can be overridden via .env for each deployment.
    consult_fee: float = Field(default=100.0, alias="CONSULT_FEE")
    consult_currency: str = Field(default="USD", alias="CONSULT_CURRENCY")

    # Toggles
    use_mock_whatsapp: bool = Field(default=False, alias="USE_MOCK_WHATSAPP")
    use_mock_email: bool = Field(default=False, alias="USE_MOCK_EMAIL")
    use_mock_razorpay: bool = Field(default=False, alias="USE_MOCK_RAZORPAY")

    # CORS
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")

    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def has_twilio(self) -> bool:
        return bool(
            self.twilio_account_sid and self.twilio_auth_token and self.twilio_whatsapp_from
        ) and not self.use_mock_whatsapp

    @property
    def has_email(self) -> bool:
        return bool(self.resend_api_key and self.email_from) and not self.use_mock_email

    @property
    def has_razorpay(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret) and not self.use_mock_razorpay


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
