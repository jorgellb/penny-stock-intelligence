"""
Custom exceptions for the application.
"""

from typing import Any


class AppException(Exception):
    """Base application exception."""

    def __init__(
        self,
        message: str,
        code: str = "APP_ERROR",
        details: dict[str, Any] | None = None,
        status_code: int = 500,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
        self.status_code = status_code


class ConfigurationError(AppException):
    """Configuration-related errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="CONFIG_ERROR", details=details, status_code=500)


class ProviderError(AppException):
    """External provider errors."""

    def __init__(
        self,
        message: str,
        provider: str,
        details: dict[str, Any] | None = None,
        status_code: int = 502,
    ):
        super().__init__(
            message,
            code="PROVIDER_ERROR",
            details={**(details or {}), "provider": provider},
            status_code=status_code,
        )
        self.provider = provider


class RateLimitError(ProviderError):
    """Rate limit exceeded."""

    def __init__(self, provider: str, retry_after: int | None = None):
        details = {"retry_after": retry_after} if retry_after else {}
        super().__init__(
            f"Rate limit exceeded for {provider}",
            provider=provider,
            details=details,
            status_code=429,
        )


class DataNotFoundError(AppException):
    """Requested data not found."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="DATA_NOT_FOUND", details=details, status_code=404)


class ValidationError(AppException):
    """Data validation errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="VALIDATION_ERROR", details=details, status_code=400)


class ScoringError(AppException):
    """Scoring calculation errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="SCORING_ERROR", details=details, status_code=500)


class ScannerError(AppException):
    """Scanner execution errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="SCANNER_ERROR", details=details, status_code=500)


class AlertError(AppException):
    """Alert dispatch errors."""

    def __init__(self, message: str, provider: str, details: dict[str, Any] | None = None):
        super().__init__(
            message,
            code="ALERT_ERROR",
            details={**(details or {}), "provider": provider},
            status_code=500,
        )


class BacktestingError(AppException):
    """Backtesting errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="BACKTEST_ERROR", details=details, status_code=500)


class TradingDisabledError(AppException):
    """Live trading attempted but disabled."""

    def __init__(self, message: str = "Live trading is disabled in this project"):
        super().__init__(message, code="TRADING_DISABLED", status_code=403)
