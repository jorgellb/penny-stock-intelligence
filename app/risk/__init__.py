"""Risk package: re-export RiskEngine for spec layout app/risk/."""

from app.scoring.risk import RiskAssessment, RiskEngine

__all__ = ["RiskEngine", "RiskAssessment"]
