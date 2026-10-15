"""Sprint A: API key auth, CORS by environment, monitor/run rate limit."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import SecurityConfig, Settings
from app.core.security import (
    SlidingWindowCounter,
    api_auth_required,
    resolve_cors_origins,
)


@pytest.fixture()
def settings_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Build Settings without YAML pollution."""

    def _make(**overrides: Any) -> Settings:
        base: dict[str, Any] = {
            "environment": "development",
            "api_key": "test-secret-key",
            "database_url": "sqlite+aiosqlite:///:memory:",
            "security": SecurityConfig(),
        }
        base.update(overrides)
        s = Settings(**base)
        monkeypatch.setattr("app.config.get_settings", lambda: s)
        monkeypatch.setattr("app.main.get_settings", lambda: s)
        monkeypatch.setattr("app.core.security.get_settings", lambda: s)
        return s

    yield _make


def test_api_auth_required_auto_from_environment() -> None:
    assert api_auth_required(Settings(environment="development", api_key="k")) is False
    assert api_auth_required(Settings(environment="production", api_key="k")) is True
    assert api_auth_required(Settings(environment="staging", api_key="k")) is True


def test_api_auth_required_explicit_override() -> None:
    s = Settings(
        environment="development",
        api_key="k",
        security=SecurityConfig(require_api_key=True),
    )
    assert api_auth_required(s) is True
    s2 = Settings(
        environment="production",
        api_key="k",
        security=SecurityConfig(require_api_key=False),
    )
    assert api_auth_required(s2) is False


def test_resolve_cors_origins_strips_wildcard_in_production() -> None:
    s = Settings(
        environment="production",
        security=SecurityConfig(cors_origins=["*", "https://dash.example.com"]),
    )
    assert resolve_cors_origins(s) == ["https://dash.example.com"]


def test_resolve_cors_origins_allows_wildcard_in_development() -> None:
    s = Settings(
        environment="development",
        security=SecurityConfig(cors_origins=["*"]),
    )
    assert resolve_cors_origins(s) == ["*"]


def test_sliding_window_blocks_after_limit() -> None:
    counter = SlidingWindowCounter(limit=2, window_seconds=60)
    assert counter.hit("client-a") is True
    assert counter.hit("client-a") is True
    assert counter.hit("client-a") is False
    assert counter.hit("client-b") is True


def _client_for(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Fresh app with lifespan DB stubs so middleware tests stay unit-scoped."""
    from app.main import create_app

    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.core.security.get_settings", lambda: settings)

    db = MagicMock()
    db.create_tables = AsyncMock()
    db.close = AsyncMock()
    monkeypatch.setattr("app.main.get_db_manager", lambda: db)

    # Avoid real monitor work when probing /monitor/run
    svc = MagicMock()
    svc.run_once = AsyncMock(return_value=[])
    svc.status = MagicMock(return_value={"running": False})
    monkeypatch.setattr("app.api.v1.endpoints.monitor.get_monitor_service", lambda: svc)

    async def _symbols(*_a: Any, **_k: Any) -> list[str]:
        return []

    monkeypatch.setattr(
        "app.repositories.WatchlistRepository.symbols",
        _symbols,
    )

    app = create_app()

    # Bypass DB session dependency for monitor/run
    async def _fake_session() -> Any:
        yield MagicMock()

    from app.core.database import get_session

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app, raise_server_exceptions=False)


def test_health_remains_public(settings_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    s = settings_factory(
        environment="production",
        security=SecurityConfig(require_api_key=True, cors_origins=["https://a.test"]),
    )
    client = _client_for(s, monkeypatch)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_missing_api_key_returns_401_when_required(
    settings_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_factory(
        environment="production",
        api_key="expected-key",
        security=SecurityConfig(require_api_key=True, cors_origins=["https://a.test"]),
    )
    client = _client_for(s, monkeypatch)
    r = client.get("/api/v1/monitor/status")
    assert r.status_code == 401
    assert "api key" in r.json()["detail"].lower()


def test_wrong_api_key_returns_401(
    settings_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_factory(
        environment="production",
        api_key="expected-key",
        security=SecurityConfig(require_api_key=True, cors_origins=["https://a.test"]),
    )
    client = _client_for(s, monkeypatch)
    r = client.get("/api/v1/monitor/status", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_valid_api_key_allows_access(
    settings_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_factory(
        environment="production",
        api_key="expected-key",
        security=SecurityConfig(require_api_key=True, cors_origins=["https://a.test"]),
    )
    client = _client_for(s, monkeypatch)
    r = client.get("/api/v1/monitor/status", headers={"X-API-Key": "expected-key"})
    assert r.status_code == 200


def test_cors_preflight_allows_configured_origin(
    settings_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_factory(
        environment="production",
        api_key="expected-key",
        security=SecurityConfig(
            require_api_key=True,
            cors_origins=["https://dash.example.com"],
        ),
    )
    client = _client_for(s, monkeypatch)
    r = client.options(
        "/api/v1/monitor/status",
        headers={
            "Origin": "https://dash.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "https://dash.example.com"


def test_cors_preflight_rejects_unknown_origin_in_production(
    settings_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_factory(
        environment="production",
        api_key="expected-key",
        security=SecurityConfig(
            require_api_key=True,
            cors_origins=["https://dash.example.com"],
        ),
    )
    client = _client_for(s, monkeypatch)
    r = client.options(
        "/api/v1/monitor/status",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Starlette omits ACAO when origin not allowed
    assert r.headers.get("access-control-allow-origin") != "https://evil.example.com"


def test_monitor_run_rate_limited(
    settings_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import security as sec_mod

    sec_mod.reset_monitor_run_limiter()
    s = settings_factory(
        environment="production",
        api_key="expected-key",
        security=SecurityConfig(
            require_api_key=True,
            cors_origins=["https://a.test"],
            monitor_run_rate_limit=2,
            rate_limit_window_seconds=60,
        ),
    )
    client = _client_for(s, monkeypatch)
    headers = {"X-API-Key": "expected-key"}
    assert client.post("/api/v1/monitor/run", headers=headers).status_code == 200
    assert client.post("/api/v1/monitor/run", headers=headers).status_code == 200
    limited = client.post("/api/v1/monitor/run", headers=headers)
    assert limited.status_code == 429
    assert "rate" in limited.json()["detail"].lower()


def test_development_allows_missing_key_by_default(
    settings_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_factory(
        environment="development",
        api_key="expected-key",
        security=SecurityConfig(cors_origins=["*"]),
    )
    client = _client_for(s, monkeypatch)
    r = client.get("/api/v1/monitor/status")
    assert r.status_code == 200
