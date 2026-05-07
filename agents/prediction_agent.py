import json
import math
import re
from datetime import timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from utils.logger import get_logger

logger = get_logger("prediction")

_CLAUDE_SYSTEM = (
    "You are a technical analysis expert. "
    "Given stock price indicators, return a JSON price outlook. "
    "Return ONLY valid JSON, no extra text."
)


class PredictionAgent:
    """
    Generates a multi-month price forecast using:
      - Linear regression trend (last 63 trading days)
      - ATR-based 95% confidence band (random-walk scaling: ATR × √t)
      - Key levels: MA50, MA200, recent high/low
    """

    def predict(self, ticker: str, months: int = 4) -> dict:
        try:
            df = yf.Ticker(ticker).history(period="1y")
            if df is None or len(df) < 60:
                return {"error": "Insufficient historical data (need 60+ days)"}

            close = df["Close"].values.astype(float)
            high  = df["High"].values.astype(float)
            low   = df["Low"].values.astype(float)
            dates = df.index.tolist()
            n = len(close)

            current_price = float(close[-1])
            forecast_trading_days = months * 21

            # ── Linear regression on last 63 trading days (~3 months) ──────────
            lookback = min(63, n)
            recent = close[-lookback:]
            x = np.arange(lookback, dtype=float)
            coeffs = np.polyfit(x, recent, 1)
            slope, intercept = float(coeffs[0]), float(coeffs[1])

            last_x = float(lookback - 1)
            forecast_prices = [
                slope * (last_x + i + 1) + intercept
                for i in range(forecast_trading_days)
            ]

            # ── ATR (14-day EWM) for confidence intervals ────────────────────
            lb1 = lookback + 1
            h  = high[-(lb1):]
            l  = low[-(lb1):]
            c  = close[-(lb1):]
            pc = c[:-1]
            h  = h[1:]
            l  = l[1:]
            c  = c[1:]
            tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
            atr = float(pd.Series(tr).ewm(span=14, min_periods=14).mean().iloc[-1])

            # 95% confidence bands: ±1.96 × ATR × √t (random walk)
            upper = [forecast_prices[i] + 1.96 * atr * math.sqrt(i + 1) for i in range(forecast_trading_days)]
            lower = [max(forecast_prices[i] - 1.96 * atr * math.sqrt(i + 1), 0.01) for i in range(forecast_trading_days)]

            # ── Future trading dates (Mon–Fri) ───────────────────────────────
            last_date = dates[-1].date() if hasattr(dates[-1], "date") else dates[-1]
            d = last_date + timedelta(days=1)
            future_dates = []
            while len(future_dates) < forecast_trading_days:
                if d.weekday() < 5:
                    future_dates.append(d.strftime("%Y-%m-%d"))
                d += timedelta(days=1)

            # ── Key levels ───────────────────────────────────────────────────
            ma50        = float(np.mean(close[-50:])) if n >= 50  else current_price
            ma200       = float(np.mean(close[-200:])) if n >= 200 else float(np.mean(close))
            recent_high = float(np.max(close[-63:]))
            recent_low  = float(np.min(close[-63:]))
            base_target = float(forecast_prices[-1])
            bull_target = max(recent_high * 1.08, base_target * 1.05)
            bear_target = min(ma50 * 0.92,         base_target * 0.92)

            # ── Trend classification ─────────────────────────────────────────
            slope_pct_per_month = (slope * 21 / current_price) * 100
            if   slope_pct_per_month >  3.0: trend = "strong_uptrend"
            elif slope_pct_per_month >  0.5: trend = "uptrend"
            elif slope_pct_per_month > -0.5: trend = "sideways"
            else:                             trend = "downtrend"

            # ── Historical data (last 6 months for chart context) ─────────────
            hist_n = min(126, n)
            def _fmt_date(ts):
                return ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]

            history = [
                {"date": _fmt_date(dates[n - hist_n + i]), "close": round(float(close[n - hist_n + i]), 2)}
                for i in range(hist_n)
            ]

            forecast_data = [
                {
                    "date":  future_dates[i],
                    "price": round(float(forecast_prices[i]), 2),
                    "upper": round(float(upper[i]), 2),
                    "lower": round(float(lower[i]), 2),
                }
                for i in range(forecast_trading_days)
            ]

            result = {
                "ticker":          ticker,
                "current_price":   round(float(current_price), 2),
                "forecast_months": months,
                "history":         history,
                "forecast":        forecast_data,
                "targets": {
                    "bull":                 round(bull_target, 2),
                    "base":                 round(base_target, 2),
                    "bear":                 round(bear_target, 2),
                    "predicted_return_pct": round((base_target - current_price) / current_price * 100, 1),
                },
                "indicators": {
                    "ma50":                round(ma50, 2),
                    "ma200":               round(ma200, 2),
                    "recent_high":         round(recent_high, 2),
                    "recent_low":          round(recent_low, 2),
                    "slope_pct_per_month": round(slope_pct_per_month, 2),
                    "atr":                 round(atr, 2),
                    "trend":               trend,
                },
            }

            claude = self._claude_analysis(ticker, result)
            if claude:
                result["claude"] = claude

            return result

        except Exception as exc:
            logger.error(f"Prediction failed for {ticker}: {exc}")
            return {"error": str(exc)}

    def _claude_analysis(self, ticker: str, prediction: dict) -> Optional[dict]:
        from config import ANTHROPIC_API_KEY
        if not ANTHROPIC_API_KEY:
            return None
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            ind = prediction["indicators"]
            tgt = prediction["targets"]
            cp  = prediction["current_price"]
            m   = prediction["forecast_months"]

            prompt = (
                f"Stock: {ticker}\n"
                f"Current price: ${cp:.2f}\n"
                f"Trend: {ind['trend']} ({ind['slope_pct_per_month']:+.2f}%/month)\n"
                f"MA50: ${ind['ma50']:.2f} | MA200: ${ind['ma200']:.2f}\n"
                f"63d High: ${ind['recent_high']:.2f} | 63d Low: ${ind['recent_low']:.2f}\n"
                f"ATR: ${ind['atr']:.2f}\n"
                f"Statistical targets ({m}m): Bull ${tgt['bull']:.2f} / Base ${tgt['base']:.2f} / Bear ${tgt['bear']:.2f}\n\n"
                f"Return a JSON object with your {m}-month outlook:\n"
                '{"outlook":"bullish"|"neutral"|"bearish",'
                '"target_low":<float>,'
                '"target_high":<float>,'
                '"summary":"<2 sentences: outlook and key risk>",'
                '"confidence":"low"|"medium"|"high"}'
            )

            resp = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=300,
                system=[{"type": "text", "text": _CLAUDE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
            )
            content = resp.content[0].text.strip()
            if content.startswith("```"):
                content = re.sub(r"^```[a-z]*\n?", "", content)
                content = re.sub(r"\n?```$", "", content.rstrip())
            return json.loads(content)
        except Exception as exc:
            logger.warning(f"Claude prediction analysis failed for {ticker}: {exc}")
            return None
