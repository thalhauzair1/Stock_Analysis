import pandas as pd

from agents.base_agent import BaseAgent


class TechnicalAgent(BaseAgent):
    name = "technical"

    def analyze(self, ticker: str, market_data: dict) -> dict:
        df = market_data.get("daily")

        if df is None or len(df) < 50:
            return {"score": 0.0, "details": {"error": "insufficient data (need 50+ days)"}}

        close = df["Close"]
        high  = df["High"]
        low   = df["Low"]

        curr_close = float(close.iloc[-1])

        # RSI (14) — manual EWM implementation, no external dependency
        rsi_val = self._rsi(close, 14)

        # 50-day simple MA
        ma50            = float(close.iloc[-50:].mean())
        above_ma50      = curr_close > ma50
        ma_distance_pct = (curr_close - ma50) / ma50 * 100 if ma50 else 0.0

        # ATR (14) — volatility context only, not scored directly
        atr_val = self._atr(high, low, close, 14)
        atr_pct = (atr_val / curr_close * 100) if curr_close else 0.0

        rsi_score = self._score_rsi(rsi_val)
        ma_score  = 1.0 if above_ma50 else 0.0

        score = 0.5 * rsi_score + 0.5 * ma_score

        return {
            "score": score,
            "details": {
                "rsi": round(rsi_val, 2),
                "rsi_score": round(rsi_score, 2),
                "ma50": round(ma50, 2),
                "above_ma50": above_ma50,
                "ma_distance_pct": round(ma_distance_pct, 2),
                "atr": round(atr_val, 2),
                "atr_pct": round(atr_pct, 2),
                "trend": "uptrend" if above_ma50 else "downtrend",
            },
        }

    # ── Indicator helpers (pure pandas/numpy, no pandas-ta dependency) ────────

    @staticmethod
    def _rsi(close: pd.Series, period: int = 14) -> float:
        delta    = close.diff()
        gain     = delta.clip(lower=0)
        loss     = (-delta).clip(lower=0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
        last_loss = float(avg_loss.iloc[-1])
        if last_loss == 0:
            return 100.0
        rs = float(avg_gain.iloc[-1]) / last_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)
        return float(tr.ewm(span=period, min_periods=period).mean().iloc[-1])

    @staticmethod
    def _score_rsi(rsi: float) -> float:
        if rsi > 80:
            return 0.0   # Will be filtered by orchestrator
        if rsi > 70:
            return 0.3   # Getting overbought
        if rsi >= 50:
            return 1.0   # Bullish momentum sweet spot
        if rsi >= 40:
            return 0.7   # Neutral-bullish
        if rsi >= 30:
            return 0.4   # Borderline oversold
        return 0.2       # Oversold
