"""
Relative Volume calculations for penny stock scanning.
"""

import numpy as np


class RVOLCalculator:
    """Calculates relative volume using multiple methods."""

    def __init__(self, lookback_sessions: int = 20):
        self.lookback_sessions = lookback_sessions

    def rvol_daily(
        self,
        current_volume: int,
        historical_volumes: np.ndarray,
    ) -> float:
        """Daily RVOL: current volume vs average daily volume."""
        if len(historical_volumes) < 5 or current_volume == 0:
            return 0.0
        avg_vol = historical_volumes[-self.lookback_sessions :].mean()
        if avg_vol == 0:
            return 0.0
        return float(current_volume / avg_vol)

    def rvol_same_time_of_day(
        self,
        current_cumulative_volume: int,
        historical_cumulative_volumes: np.ndarray,
    ) -> float:
        """RVOL comparing cumulative volume at same time of day."""
        if len(historical_cumulative_volumes) < 5 or current_cumulative_volume == 0:
            return 0.0
        avg_cum_vol = np.mean(historical_cumulative_volumes)
        if avg_cum_vol == 0:
            return 0.0
        return float(current_cumulative_volume / avg_cum_vol)

    def rvol_intraday(
        self,
        current_interval_volume: int,
        historical_interval_volumes: np.ndarray,
        interval_minutes: int = 5,
    ) -> float:
        """RVOL for specific intraday intervals (5m, 15m, 30m)."""
        if len(historical_interval_volumes) < 5 or current_interval_volume == 0:
            return 0.0
        avg_interval_vol = historical_interval_volumes.mean()
        if avg_interval_vol == 0:
            return 0.0
        return float(current_interval_volume / avg_interval_vol)

    def compute_all(
        self,
        current_total_volume: int,
        current_interval_volume: int,
        historical_daily_volumes: np.ndarray,
        historical_interval_volumes: np.ndarray,
        historical_same_time_volumes: np.ndarray,
        interval_minutes: int = 5,
    ) -> dict[str, float]:
        """Compute all RVOL metrics."""
        return {
            "rvol_daily": self.rvol_daily(current_total_volume, historical_daily_volumes),
            "rvol_same_time": self.rvol_same_time_of_day(
                current_total_volume, historical_same_time_volumes
            ),
            "rvol_5m": self.rvol_intraday(current_interval_volume, historical_interval_volumes, 5),
            "rvol_15m": self.rvol_intraday(
                current_interval_volume, historical_interval_volumes, 15
            ),
            "rvol_30m": self.rvol_intraday(
                current_interval_volume, historical_interval_volumes, 30
            ),
        }

    def volume_acceleration(
        self,
        recent_volumes: np.ndarray,
        older_volumes: np.ndarray,
    ) -> float | None:
        """Calculate volume acceleration ratio."""
        if len(recent_volumes) == 0 or len(older_volumes) == 0:
            return None
        recent_avg = recent_volumes.mean()
        older_avg = older_volumes.mean()
        if older_avg == 0:
            return None
        return float((recent_avg - older_avg) / older_avg)

    def volume_surge_detected(
        self,
        current_volume: int,
        historical_volumes: np.ndarray,
        threshold: float = 2.0,
    ) -> bool:
        """Detect if there's a significant volume surge."""
        rvol = self.rvol_daily(current_volume, historical_volumes)
        return rvol >= threshold

    def intraday_volume_curve(
        self,
        volumes_by_interval: list[int],
        session_minutes: int = 390,  # 9:30 AM to 4:00 PM
    ) -> dict[str, float]:
        """Calculate intraday volume distribution curve."""
        total = sum(volumes_by_interval)
        if total == 0:
            return {}
        intervals = len(volumes_by_interval)
        return {
            f"{i * session_minutes // intervals}min": vol / total
            for i, vol in enumerate(volumes_by_interval)
            if vol > 0
        }


def detect_abnormal_volume(
    current_volume: int,
    historical_volumes: np.ndarray,
    window: int = 20,
    z_threshold: float = 2.0,
) -> dict[str, float]:
    """Detect abnormal volume using z-score."""
    if len(historical_volumes) < window or current_volume == 0:
        return {"abnormal": False, "z_score": 0.0, "rvol": 0.0}

    recent = historical_volumes[-window:]
    mean_vol = recent.mean()
    std_vol = recent.std()

    if std_vol == 0:
        return {"abnormal": False, "z_score": 0.0, "rvol": 0.0}

    z_score = (current_volume - mean_vol) / std_vol
    rvol = current_volume / mean_vol if mean_vol > 0 else 0.0

    return {
        "abnormal": abs(z_score) >= z_threshold,
        "z_score": z_score,
        "rvol": rvol,
    }


def detect_abnormal_price_move(
    current_change_pct: float,
    historical_changes: np.ndarray,
    window: int = 20,
    z_threshold: float = 2.0,
) -> dict[str, float]:
    """Detect abnormal price moves using z-score."""
    if len(historical_changes) < window:
        return {"abnormal": False, "z_score": 0.0}

    recent = historical_changes[-window:]
    mean_change = recent.mean()
    std_change = recent.std()

    if std_change == 0:
        return {"abnormal": False, "z_score": 0.0}

    z_score = (current_change_pct - mean_change) / std_change

    return {
        "abnormal": abs(z_score) >= z_threshold,
        "z_score": z_score,
    }
