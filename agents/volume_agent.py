from agents.base_agent import BaseAgent


class VolumeAgent(BaseAgent):
    name = "volume"

    def analyze(self, ticker: str, market_data: dict) -> dict:
        df = market_data.get("daily")

        if df is None or len(df) < 22:
            return {"score": 0.0, "details": {"error": "insufficient data (need 22+ days)"}}

        volume      = df["Volume"]
        current_vol = int(volume.iloc[-1])
        avg_vol_20d = float(volume.iloc[-21:-1].mean())

        if avg_vol_20d == 0:
            return {"score": 0.0, "details": {"error": "zero average volume"}}

        rvol = current_vol / avg_vol_20d

        # RVOL=1 → 0.0 | RVOL=2 → 0.5 | RVOL≥3 → 1.0
        score = max(0.0, min((rvol - 1.0) / 2.0, 1.0))

        if rvol >= 3.0:
            strength = "very strong"
        elif rvol >= 2.0:
            strength = "strong"
        elif rvol >= 1.5:
            strength = "elevated"
        else:
            strength = "normal"

        return {
            "score": score,
            "details": {
                "current_volume": current_vol,
                "avg_volume_20d": int(avg_vol_20d),
                "rvol": round(rvol, 2),
                "strength": strength,
            },
        }
