from agents.base_agent import BaseAgent


class VWAPAgent(BaseAgent):
    name = "vwap"

    def analyze(self, ticker: str, market_data: dict) -> dict:
        intraday = market_data.get("intraday")
        daily    = market_data.get("daily")

        vwap   = None
        method = "unknown"

        # Primary: true intraday VWAP from minute/5-min bars
        if intraday is not None and len(intraday) > 5:
            tp  = (intraday["High"] + intraday["Low"] + intraday["Close"]) / 3
            vol = intraday["Volume"]
            cum_vol = float(vol.sum())
            if cum_vol > 0:
                vwap   = float((tp * vol).sum() / cum_vol)
                method = "intraday_5m"

        # Fallback: approximate from today's daily OHLC candle
        if vwap is None and daily is not None and len(daily) >= 1:
            row    = daily.iloc[-1]
            vwap   = float((row["High"] + row["Low"] + row["Close"]) / 3)
            method = "daily_ohlc_approx"

        if vwap is None or daily is None:
            return {"score": 0.5, "details": {"note": "VWAP unavailable — neutral score"}}

        curr = float(daily["Close"].iloc[-1])
        pct  = (curr - vwap) / vwap * 100 if vwap else 0.0

        # Above VWAP → bullish; graded by distance (±5 % maps to 0.5 ± 0.5)
        score = max(0.0, min(0.5 + pct / 10.0, 1.0))

        return {
            "score": score,
            "details": {
                "vwap": round(vwap, 2),
                "current_price": round(curr, 2),
                "price_vs_vwap_pct": round(pct, 2),
                "above_vwap": curr > vwap,
                "method": method,
            },
        }
