"""Unit: walk-forward splits/report + score calibration."""

from datetime import datetime

from app.backtesting import calibrate_by_score, walk_forward_report, walk_forward_splits


def _items(n: int = 12) -> list[dict]:
    return [
        {
            "symbol": f"S{i}",
            "date": f"2026-01-{i + 1:02d}",
            "score": 60 + (i % 4) * 10,
            "return_pct": float(i - 5),
        }
        for i in range(n)
    ]


def test_splits_chronological_no_leakage() -> None:
    items = _items()[::-1]  # shuffled input must still split in order
    folds = walk_forward_splits(items, n_splits=3)
    assert len(folds) == 3
    for i, (train, test) in enumerate(folds):
        assert max(t["date"] for t in train) < min(t["date"] for t in test)
        assert len(test) == 3
        assert len(train) == 3 * (i + 1)  # expanding window
    # expanding window: train grows
    assert len(folds[1][0]) > len(folds[0][0])


def test_splits_reject_bad_input() -> None:
    assert walk_forward_splits([], n_splits=3) == []
    assert walk_forward_splits(_items(2), n_splits=3) == []
    assert walk_forward_splits([{"symbol": "X"}], n_splits=2) == []  # no date


def test_report_metrics_and_means() -> None:
    rep = walk_forward_report(_items(), n_splits=3)
    assert len(rep["folds"]) == 3
    first = rep["folds"][0]
    assert first["n_train"] == 3 and first["n_test"] == 3
    assert first["metrics"]["number_of_signals"] == 3.0
    assert set(rep["mean"]) == {"win_rate", "average_return", "median_return", "expectancy"}


def test_report_empty() -> None:
    assert walk_forward_report([], n_splits=3) == {"folds": []}


def test_calibrate_by_score_bands() -> None:
    items = [
        {"score": 55, "return_pct": 1.0},
        {"score": 58, "return_pct": 3.0},
        {"score": 75, "return_pct": -2.0},
        {"score": 95, "return_pct": 10.0},
        {"score": 20, "return_pct": 100.0},  # below bands: ignored
    ]
    cal = calibrate_by_score(items)
    assert cal["50-60"]["n"] == 2.0
    assert cal["50-60"]["average_return"] == 2.0
    assert cal["70-80"]["average_return"] == -2.0
    assert cal["90-100"]["win_rate"] == 100.0
    assert cal["80-90"]["n"] == 0.0


def test_calibrate_accepts_datetime_objects() -> None:
    items = [{"date": datetime(2026, 1, 5), "score": 80, "return_pct": 2.0}]
    assert walk_forward_splits(items * 4, n_splits=1)[0][1]
