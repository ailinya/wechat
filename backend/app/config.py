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

    # 异步执行（任务 2.3）：Celery broker 与任务运行约束
    redis_url: str = Field(
        default="redis://127.0.0.1:6379/0",
        validation_alias="REDIS_URL",
    )
    celery_task_always_eager: bool = Field(
        default=False,
        validation_alias="CELERY_TASK_ALWAYS_EAGER",
    )
    job_soft_time_limit_seconds: int = Field(
        default=300, ge=1, validation_alias="JOB_SOFT_TIME_LIMIT_SECONDS",
    )
    job_max_attempts: int = Field(
        default=3, ge=1, validation_alias="JOB_MAX_ATTEMPTS",
    )
    job_retry_backoff_seconds: int = Field(
        default=5, ge=0, validation_alias="JOB_RETRY_BACKOFF_SECONDS",
    )
    job_stale_timeout_minutes: int = Field(
        default=30, ge=1, validation_alias="JOB_STALE_TIMEOUT_MINUTES",
    )

    # 对象存储（任务 2.6）：RustFS S3 兼容端点与授权有效期
    rustfs_endpoint: str = Field(
        default="http://127.0.0.1:9000",
        validation_alias="RUSTFS_ENDPOINT",
    )
    rustfs_access_key: str = Field(default="", validation_alias="RUSTFS_ACCESS_KEY")
    rustfs_secret_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="RUSTFS_SECRET_KEY",
    )
    rustfs_bucket: str = Field(default="attachments", validation_alias="RUSTFS_BUCKET")
    upload_grant_ttl_minutes: int = Field(
        default=15, ge=1, validation_alias="UPLOAD_GRANT_TTL_MINUTES",
    )
    download_grant_ttl_minutes: int = Field(
        default=5, ge=1, validation_alias="DOWNLOAD_GRANT_TTL_MINUTES",
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
