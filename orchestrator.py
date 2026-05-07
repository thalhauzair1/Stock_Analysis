import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import yfinance as yf

from agents import (
    BreakoutAgent, MomentumAgent, NewsAgent, SmartMoneyAgent,
    TechnicalAgent, VolumeAgent, VWAPAgent,
)
from config import (
    MAX_RSI_THRESHOLD, MIN_AVG_VOLUME, MIN_PRICE, STOCK_UNIVERSE,
    TOP_N_RESULTS, WEIGHTS,
)
from database import RankingModel, SessionLocal
from utils.logger import get_logger

logger = get_logger("orchestrator")


class Orchestrator:
    def __init__(self) -> None:
        self._agents = {
            "momentum":    MomentumAgent(),
            "volume":      VolumeAgent(),
            "technical":   TechnicalAgent(),
            "vwap":        VWAPAgent(),
            "breakout":    BreakoutAgent(),
            "sentiment":   NewsAgent(),
            "smart_money": SmartMoneyAgent(),
        }

    # ── Public entry-point ────────────────────────────────────────────────────

    def run(self) -> dict:
        run_id = uuid.uuid4().hex[:8]
        t0     = time.time()
        logger.info(f"{'='*60}")
        logger.info(f"Run {run_id} started — {datetime.now(timezone.utc).isoformat()}Z")

        # 1. Bulk-fetch market data
        market_map = self._fetch_market_data(STOCK_UNIVERSE)

        # 2. Score every ticker
        results: list[dict] = []
        for ticker in STOCK_UNIVERSE:
            if ticker in ("SPY", "QQQ"):
                continue
            mdata = market_map.get(ticker, {})
            mdata["spy_daily"] = (market_map.get("SPY") or {}).get("daily")
            result = self._score_ticker(ticker, mdata, run_id)
            if result:
                results.append(result)

        logger.info(f"Scored {len(results)} tickers")

        # 3. Filter low-signal / risky stocks
        passed = self._filter(results)
        logger.info(f"After filter: {len(passed)} tickers remain")

        # 4. Rank & take top-N
        ranked = sorted(passed, key=lambda x: x["final_score"], reverse=True)
        top    = ranked[:TOP_N_RESULTS]
        for i, r in enumerate(top, start=1):
            r["rank"] = i

        # 5. Persist
        self._save(top, run_id)

        elapsed = round(time.time() - t0, 1)
        logger.info(f"Run {run_id} done in {elapsed}s — top: {[r['ticker'] for r in top]}")

        return {
            "run_id":           run_id,
            "timestamp":        datetime.now(timezone.utc).isoformat(),
            "stocks_analyzed":  len(results),
            "top_30":           top,
            "duration_seconds": elapsed,
        }

    # ── Data fetching ─────────────────────────────────────────────────────────

    def _fetch_market_data(self, tickers: list[str]) -> dict[str, dict]:
        logger.info(f"Fetching 65-day daily data for {len(tickers)} tickers …")
        market_map: dict[str, dict] = {t: {} for t in tickers}

        try:
            raw = yf.download(
                tickers=" ".join(tickers),
                period="65d",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            for ticker in tickers:
                df = self._extract_df(raw, ticker, len(tickers))
                market_map[ticker]["daily"] = df
        except Exception as exc:
            logger.error(f"Bulk download error: {exc}")

        # Intraday for VWAP (best-effort, skip ETFs)
        logger.info("Fetching intraday bars for VWAP …")
        for ticker in tickers:
            if ticker in ("SPY", "QQQ"):
                continue
            try:
                idf = yf.Ticker(ticker).history(period="1d", interval="5m")
                market_map[ticker]["intraday"] = idf if not idf.empty else None
            except Exception as exc:
                logger.debug(f"Intraday {ticker}: {exc}")
                market_map[ticker]["intraday"] = None

        return market_map

    @staticmethod
    def _extract_df(raw: pd.DataFrame, ticker: str, n_tickers: int) -> Optional[pd.DataFrame]:
        try:
            if n_tickers == 1:
                df = raw
            elif isinstance(raw.columns, pd.MultiIndex):
                lvl0 = raw.columns.get_level_values(0).unique().tolist()
                lvl1 = raw.columns.get_level_values(1).unique().tolist()

                if ticker in lvl1:
                    df = raw.xs(ticker, axis=1, level=1)
                elif ticker in lvl0:
                    df = raw[ticker]
                else:
                    return None
            else:
                return None

            df = df.dropna(how="all")
            if df.empty:
                return None

            # Flatten any residual MultiIndex columns (yfinance ≥1.0 quirk)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

            return df
        except Exception:
            return None

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score_ticker(self, ticker: str, mdata: dict, run_id: str) -> Optional[dict]:
        scores: dict[str, float] = {}
        details: dict[str, dict] = {}

        for name, agent in self._agents.items():
            res          = agent.safe_analyze(ticker, mdata)
            scores[name] = res["score"]
            details[name] = res["details"]

        # Skip if every agent returned 0 (data entirely unavailable)
        if all(v == 0.0 for v in scores.values()):
            logger.debug(f"Skipping {ticker}: all-zero scores")
            return None

        final = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)

        curr_close = details.get("momentum", {}).get("curr_close")

        return {
            "ticker":           ticker,
            "curr_close":       curr_close,
            "final_score":      round(final, 4),
            "momentum_score":   round(scores["momentum"],    4),
            "volume_score":     round(scores["volume"],      4),
            "technical_score":  round(scores["technical"],   4),
            "vwap_score":       round(scores["vwap"],        4),
            "breakout_score":   round(scores["breakout"],    4),
            "sentiment_score":  round(scores["sentiment"],   4),
            "smart_money_score": round(scores["smart_money"], 4),
            "explanation":      self._explain(ticker, scores, details),
            "details":          details,
            "run_id":           run_id,
            "timestamp":        datetime.now(timezone.utc).isoformat(),
        }

    # ── Filters ───────────────────────────────────────────────────────────────

    def _filter(self, results: list[dict]) -> list[dict]:
        passed: list[dict] = []
        for r in results:
            ticker = r["ticker"]

            # Low average volume
            avg_vol = r["details"].get("volume", {}).get("avg_volume_20d", 0)
            if 0 < avg_vol < MIN_AVG_VOLUME:
                logger.debug(f"Filtered {ticker}: avg vol {avg_vol:,} < {MIN_AVG_VOLUME:,}")
                continue

            # Extremely overbought RSI
            rsi = r["details"].get("technical", {}).get("rsi", 50)
            if rsi > MAX_RSI_THRESHOLD:
                logger.debug(f"Filtered {ticker}: RSI {rsi:.1f} > {MAX_RSI_THRESHOLD}")
                continue

            # Price too low (penny stock)
            curr = r["details"].get("momentum", {}).get("curr_close", 999)
            if 0 < curr < MIN_PRICE:
                logger.debug(f"Filtered {ticker}: price ${curr:.2f} < ${MIN_PRICE}")
                continue

            # No breakout AND no positive news — very low signal
            if r["breakout_score"] == 0.0 and r["sentiment_score"] <= 0.5:
                logger.debug(f"Filtered {ticker}: no breakout + no positive news")
                continue

            passed.append(r)
        return passed

    # ── Human-readable explanation ────────────────────────────────────────────

    @staticmethod
    def _explain(ticker: str, scores: dict, details: dict) -> str:
        parts: list[str] = []

        # Momentum
        md  = details.get("momentum", {})
        pct = md.get("price_change_pct", 0)
        if pct > 0:
            parts.append(f"momentum +{pct:.1f}%")

        # Volume
        vd  = details.get("volume", {})
        rv  = vd.get("rvol", 1.0)
        st  = vd.get("strength", "")
        if rv >= 1.5:
            parts.append(f"{st} volume ({rv:.1f}x avg)")

        # Technical
        td = details.get("technical", {})
        if td.get("above_ma50"):
            parts.append("above 50-MA")
        rsi = td.get("rsi", 0)
        if 50 <= rsi <= 70:
            parts.append(f"RSI {rsi:.0f}")

        # VWAP
        if details.get("vwap", {}).get("above_vwap"):
            parts.append("above VWAP")

        # Breakout
        bd  = details.get("breakout", {})
        sig = bd.get("signal", "")
        if sig == "confirmed_breakout":
            parts.append(f"confirmed 20-day breakout (+{bd.get('breakout_pct', 0):.1f}%)")
        elif sig == "unconfirmed_breakout":
            parts.append("at 20-day high")
        elif sig == "near_resistance":
            parts.append("near 20-day resistance")

        # News
        nd   = details.get("sentiment", {})
        cats = nd.get("catalysts", [])
        if cats:
            parts.append(f"catalyst: {', '.join(cats[:2])}")
        elif scores.get("sentiment", 0.5) > 0.6:
            parts.append("positive news")

        # Smart money
        sm = details.get("smart_money", {})
        if sm.get("politician_buys", 0):
            parts.append(f"{sm['politician_buys']} politician buy(s)")
        if sm.get("insider_buys", 0):
            parts.append(f"{sm['insider_buys']} insider buy(s)")

        return (f"{ticker}: " + "; ".join(parts)) if parts else f"{ticker}: moderate multi-factor signal"

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self, rankings: list[dict], run_id: str) -> None:
        db = SessionLocal()
        try:
            for r in rankings:
                db.add(RankingModel(
                    run_id=run_id,
                    timestamp=datetime.now(timezone.utc),
                    rank=r.get("rank", 0),
                    ticker=r["ticker"],
                    final_score=r["final_score"],
                    momentum_score=r["momentum_score"],
                    volume_score=r["volume_score"],
                    technical_score=r["technical_score"],
                    vwap_score=r["vwap_score"],
                    breakout_score=r["breakout_score"],
                    sentiment_score=r["sentiment_score"],
                    smart_money_score=r["smart_money_score"],
                    explanation=r["explanation"],
                    curr_close=r.get("details", {}).get("momentum", {}).get("curr_close"),
                    details=json.dumps(r.get("details", {}), default=str),
                ))
            db.commit()
            logger.info(f"Saved {len(rankings)} rankings (run={run_id})")
        except Exception as exc:
            db.rollback()
            logger.error(f"DB save error: {exc}")
        finally:
            db.close()
