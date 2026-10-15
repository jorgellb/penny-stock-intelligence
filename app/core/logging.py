"""
Structured logging configuration using structlog.
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

from app.config import get_settings


def add_app_context(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Add application context to log entries."""
    event_dict["app"] = "penny-stock-intelligence"
    event_dict["environment"] = get_settings().environment
    return event_dict


def sanitize_secrets(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> Any:
    """Remove sensitive data from logs."""
    sensitive_keys = {
        "api_key",
        "api_keys",
        "password",
        "secret",
        "token",
        "authorization",
        "auth",
        "credential",
        "key",
        "alpha_vantage_api_key",
        "finnhub_api_key",
        "polygon_api_key",
        "twelve_data_api_key",
        "openai_api_key",
        "anthropic_api_key",
        "telegram_bot_token",
        "discord_webhook_url",
        "smtp_password",
        "webhook_secret",
        "database_url",
        "redis_url",
    }

    def _sanitize(obj: Any, path: str = "") -> Any:
        if isinstance(obj, dict):
            return {
                k: _sanitize(v, f"{path}.{k}")
                if k.lower() not in sensitive_keys
                else "***REDACTED***"
                for k, v in obj.items()
            }
        elif isinstance(obj, list):
            return [_sanitize(item, f"{path}[{i}]") for i, item in enumerate(obj)]
        return obj

    return _sanitize(event_dict)


def setup_logging() -> None:
    """Configure structured logging."""
    settings = get_settings()

    # Standard library logging setup
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )

    # Configure structlog
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        add_app_context,
        sanitize_secrets,
    ]

    if settings.logging.format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,  # type: ignore[arg-type]
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set log levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)


def get_logger(name: str) -> Any:
    """Get a structured logger instance."""
    return structlog.get_logger(name)
