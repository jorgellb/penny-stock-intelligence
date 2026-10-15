"""Test configuration."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def configure_app():
    """Configure the app for testing."""
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DEBUG"] = "true"
    os.environ["PAPER_MODE"] = "true"
    os.environ["LIVE_TRADING"] = "false"
    os.environ["TESTING"] = "true"
