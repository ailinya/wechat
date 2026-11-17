from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    secret_key: SecretStr = Field(
        validation_alias="APP_SECRET_KEY",
        min_length=32,
    )
    app_name: str = Field(
        default="智媒助手 API",
        validation_alias="APP_NAME",
    )
    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias="APP_ENV",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        validation_alias="APP_LOG_LEVEL",
    )

    # 数据库（凭据来自环境变量，不写入仓库）
    database_url: str | None = Field(
        default=None,
        validation_alias="DATABASE_URL",
    )

    # 会话有效期（分钟）与 Cookie/CSRF 策略
    session_ttl_minutes: int = Field(default=480, ge=1, validation_alias="SESSION_TTL_MINUTES")
    session_cookie_name: str = Field(
        default="wetchat_session", validation_alias="SESSION_COOKIE_NAME"
    )
    session_cookie_secure: bool = Field(
        default=False, validation_alias="SESSION_COOKIE_SECURE"
    )
    session_cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax", validation_alias="SESSION_COOKIE_SAMESITE"
    )
    csrf_header_name: str = Field(
        default="X-CSRF-Token", validation_alias="CSRF_HEADER_NAME"
    )
    csrf_cookie_name: str = Field(
        default="wetchat_csrf", validation_alias="CSRF_COOKIE_NAME"
    )


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        issues = []
        for error in exc.errors():
            location = str(error["loc"][-1]) if error["loc"] else "configuration"
            variable = "APP_SECRET_KEY" if location in {"secret_key", "APP_SECRET_KEY"} else location
            if error["type"] == "missing":
                issues.append(f"{variable} is required")
            elif variable == "APP_SECRET_KEY":
                issues.append("APP_SECRET_KEY must contain at least 32 characters")
            else:
                issues.append(f"{variable} has an invalid value")
        raise ConfigurationError("Invalid application configuration: " + "; ".join(issues)) from None
