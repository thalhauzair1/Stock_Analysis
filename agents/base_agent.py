from abc import ABC, abstractmethod

from utils.logger import get_logger


class BaseAgent(ABC):
    name: str = "base"

    def __init__(self) -> None:
        self.logger = get_logger(f"agents.{self.name}")

    @abstractmethod
    def analyze(self, ticker: str, market_data: dict) -> dict:
        """
        Return {"score": float [0,1], "details": dict}.
        Raise freely — safe_analyze() catches everything.
        """
        ...

    def safe_analyze(self, ticker: str, market_data: dict) -> dict:
        try:
            result = self.analyze(ticker, market_data)
            result.setdefault("score", 0.0)
            result.setdefault("details", {})
            result["score"] = float(max(0.0, min(1.0, result["score"])))
            return result
        except Exception as exc:
            self.logger.warning(f"[{self.name}] {ticker}: {exc}")
            return {"score": 0.0, "details": {"error": str(exc)}}
