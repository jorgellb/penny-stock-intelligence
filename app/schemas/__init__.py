"""Pydantic response schemas (thin wrappers over domain models)."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class ScanResponse(BaseModel):
    timestamp: datetime
    total_symbols: int
    eligible_count: int
    excluded_count: int
    results: list
    duration_ms: int | None = None


class PremarketScanResponse(BaseModel):
    rankings: list
    timestamp: datetime


class IntradayScanResponse(BaseModel):
    rankings: list
    timestamp: datetime
    market_status: str


class ScoreResponse(BaseModel):
    symbol: str
    final_score: int
    raw_score: int
    risk_penalty: int
    data_quality: str
    explanation: str
