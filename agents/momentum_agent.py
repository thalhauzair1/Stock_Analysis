import pandas as pd

from agents.base_agent import BaseAgent


class MomentumAgent(BaseAgent):
    name = "momentum"

    def analyze(self, ticker: str, market_data: dict) -> dict:
        df     = market_data.get("daily")
        spy_df = market_data.get("spy_daily")

        if df is None or len(df) < 2:
            return {"score": 0.0, "details": {"error": "insufficient data"}}

        prev_close = float(df["Close"].iloc[-2])
        curr_close = float(df["Close"].iloc[-1])

        if prev_close == 0:
            return {"score": 0.0, "details": {"error": "zero prev close"}}

        price_change_pct = (curr_close - prev_close) / prev_close * 100

        # Relative strength vs SPY
        rel_strength = 0.0
        if spy_df is not None and len(spy_df) >= 2:
            spy_close = spy_df["Close"]
            # Squeeze in case yfinance returns a single-column DataFrame
            if hasattr(spy_close, "squeeze"):
                spy_close = spy_close.squeeze()
            spy_prev = float(spy_close.iloc[-2])
            spy_curr = float(spy_close.iloc[-1])
            if spy_prev:
                spy_chg  = (spy_curr - spy_prev) / spy_prev * 100
                rel_strength = price_change_pct - spy_chg

        # 5 % gain → 0.5 score ; 10 % → 1.0 ; negative → 0
        score = max(0.0, min(price_change_pct / 10.0, 1.0))

        # Small boost for outperforming SPY by >5 %
        if rel_strength > 5:
            score = min(score + 0.10, 1.0)

        return {
            "score": score,
            "details": {
                "price_change_pct": round(price_change_pct, 2),
                "relative_strength_vs_spy": round(rel_strength, 2),
                "prev_close": round(prev_close, 2),
                "curr_close": round(curr_close, 2),
            },
        }
