from agents.base_agent import BaseAgent


class BreakoutAgent(BaseAgent):
    name = "breakout"

    def analyze(self, ticker: str, market_data: dict) -> dict:
        df = market_data.get("daily")

        if df is None or len(df) < 22:
            return {"score": 0.0, "details": {"error": "insufficient data (need 22+ days)"}}

        close = df["Close"]
        vol   = df["Volume"]

        curr_close  = float(close.iloc[-1])
        curr_vol    = float(vol.iloc[-1])
        high_20d    = float(close.iloc[-21:-1].max())   # 20-day high, excluding today
        avg_vol_20d = float(vol.iloc[-21:-1].mean())

        is_20d_high      = curr_close > high_20d
        is_vol_confirmed = avg_vol_20d > 0 and curr_vol > avg_vol_20d * 1.5

        breakout_pct = (curr_close - high_20d) / high_20d * 100 if high_20d else 0.0
        proximity    = curr_close / high_20d if high_20d else 0.0

        if is_20d_high and is_vol_confirmed:
            score  = min(0.75 + breakout_pct / 20.0, 1.0)
            signal = "confirmed_breakout"
        elif is_20d_high:
            score  = 0.50
            signal = "unconfirmed_breakout"
        elif proximity >= 0.98:
            score  = 0.30 + (proximity - 0.98) * 10.0
            signal = "near_resistance"
        elif is_vol_confirmed:
            score  = 0.25
            signal = "volume_spike_only"
        else:
            score  = 0.0
            signal = "no_breakout"

        return {
            "score": max(0.0, min(score, 1.0)),
            "details": {
                "current_close": round(curr_close, 2),
                "high_20d": round(high_20d, 2),
                "is_20d_high": is_20d_high,
                "breakout_pct": round(breakout_pct, 2),
                "current_volume": int(curr_vol),
                "avg_volume_20d": int(avg_vol_20d),
                "is_volume_confirmed": is_vol_confirmed,
                "signal": signal,
            },
        }
