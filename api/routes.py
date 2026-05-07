from datetime import datetime, timezone
from typing import Optional

import sqlalchemy
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

import state
from config import ANTHROPIC_API_KEY, NEWS_API_KEY, OPENAI_API_KEY
from database import PortfolioHolding, PortfolioSell, RankingModel, get_db
from models.schemas import AddHoldingRequest, HealthResponse, RecordSellRequest
from utils.logger import get_logger

logger = get_logger("api")
router = APIRouter()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(sqlalchemy.text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    last = state.get_result()
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc),
        db_ok=db_ok,
        last_run=datetime.fromisoformat(last["timestamp"]) if last else None,
        stocks_analyzed=last["stocks_analyzed"] if last else 0,
        openai_enabled=bool(OPENAI_API_KEY),
        anthropic_enabled=bool(ANTHROPIC_API_KEY),
        news_enabled=bool(NEWS_API_KEY),
    )


# ── Top stocks ────────────────────────────────────────────────────────────────

@router.get("/top-stocks", tags=["rankings"])
def top_stocks(db: Session = Depends(get_db), limit: int = 30):
    """Return the latest top-N ranked stocks, enriched with sector/industry."""
    from utils.sectors import get_sector_info

    last = state.get_result()
    if last:
        stocks = last["top_30"][:limit]
    else:
        latest = (
            db.query(RankingModel.run_id)
            .order_by(RankingModel.timestamp.desc())
            .first()
        )
        if not latest:
            raise HTTPException(
                status_code=404,
                detail="No rankings yet. POST /run to trigger an analysis.",
            )
        rows = (
            db.query(RankingModel)
            .filter(RankingModel.run_id == latest.run_id)
            .order_by(RankingModel.rank.asc())
            .limit(limit)
            .all()
        )
        stocks = [_row_to_dict(r) for r in rows]

    for s in stocks:
        info = get_sector_info(s["ticker"])
        s["sector"]   = info["sector"]
        s["industry"] = info["industry"]
    return stocks


# ── Sectors ───────────────────────────────────────────────────────────────────

@router.get("/sectors", tags=["rankings"])
def get_sectors(db: Session = Depends(get_db)):
    """Return sector performance from the latest run (avg % change + avg score)."""
    from utils.sectors import get_sector_info, SECTOR_COLORS

    last = state.get_result()
    if last:
        stocks = last["top_30"]
    else:
        latest = (
            db.query(RankingModel.run_id)
            .order_by(RankingModel.timestamp.desc())
            .first()
        )
        if not latest:
            return []
        rows = (
            db.query(RankingModel)
            .filter(RankingModel.run_id == latest.run_id)
            .all()
        )
        stocks = [_row_to_dict(r) for r in rows]

    buckets: dict[str, dict] = {}
    for s in stocks:
        ticker = s["ticker"]
        info   = get_sector_info(ticker)
        sector = info["sector"]
        if sector == "ETF":
            continue

        chg = None
        details = s.get("details") or {}
        mom = details.get("momentum") or {}
        if isinstance(mom, dict):
            chg = mom.get("price_change_pct")

        if sector not in buckets:
            buckets[sector] = {
                "sector":      sector,
                "color":       SECTOR_COLORS.get(sector, "#64748b"),
                "scores":      [],
                "changes":     [],
                "stocks":      [],
            }
        buckets[sector]["scores"].append(s["final_score"])
        if chg is not None:
            buckets[sector]["changes"].append(chg)
        buckets[sector]["stocks"].append({
            "ticker":   ticker,
            "industry": info["industry"],
            "score":    round(s["final_score"], 3),
            "change":   round(chg, 2) if chg is not None else None,
        })

    result = []
    for data in buckets.values():
        scores  = data.pop("scores")
        changes = data.pop("changes")
        data["avg_score"]      = round(sum(scores)  / len(scores),  3) if scores  else 0.0
        data["avg_change_pct"] = round(sum(changes) / len(changes), 2) if changes else None
        data["stock_count"]    = len(data["stocks"])
        result.append(data)

    return sorted(result, key=lambda x: x["avg_change_pct"] or -999, reverse=True)


# ── Single stock ──────────────────────────────────────────────────────────────

@router.get("/stock/{ticker}", tags=["rankings"])
def get_stock(ticker: str, db: Session = Depends(get_db)):
    """Return the most recent ranking for a specific ticker."""
    row = (
        db.query(RankingModel)
        .filter(RankingModel.ticker == ticker.upper())
        .order_by(RankingModel.timestamp.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No data for {ticker.upper()}")
    return _row_to_dict(row)


# ── Per-agent signals ─────────────────────────────────────────────────────────

@router.get("/signals/{ticker}", tags=["signals"])
def get_signals(ticker: str):
    """Return full per-agent signal breakdown for a ticker (current run only)."""
    last = state.get_result()
    if not last:
        raise HTTPException(status_code=404, detail="No run data. POST /run first.")

    ticker = ticker.upper()
    stock  = next((s for s in last["top_30"] if s["ticker"] == ticker), None)
    if not stock:
        raise HTTPException(
            status_code=404,
            detail=f"{ticker} not in current top results. Check /top-stocks.",
        )

    return {
        "ticker":      ticker,
        "final_score": stock["final_score"],
        "explanation": stock["explanation"],
        "run_id":      stock["run_id"],
        "signals": {
            name: {
                "score":   stock[f"{name}_score"],
                "weight":  _weight(name),
                "details": stock["details"].get(name, {}),
            }
            for name in ("momentum", "volume", "technical", "vwap",
                         "breakout", "sentiment", "smart_money")
        },
    }


# ── Manual trigger ────────────────────────────────────────────────────────────

@router.post("/run", tags=["system"])
def trigger_run(background: BackgroundTasks):
    """Manually kick off a full analysis pipeline run."""
    def _job():
        from orchestrator import Orchestrator
        result = Orchestrator().run()
        state.set_result(result)

    background.add_task(_job)
    return {"message": "Analysis started in background. Poll /top-stocks shortly."}


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/history", tags=["rankings"])
def history(db: Session = Depends(get_db), limit: int = 50):
    """Return the last N ranking records across all runs."""
    rows = (
        db.query(RankingModel)
        .order_by(RankingModel.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [_row_to_dict(r) for r in rows]


# ── Portfolio ─────────────────────────────────────────────────────────────

@router.get("/portfolio", tags=["portfolio"])
def get_portfolio(db: Session = Depends(get_db)):
    """List all manual holdings with live P&L."""
    holdings = (
        db.query(PortfolioHolding)
        .order_by(PortfolioHolding.added_at.asc())
        .all()
    )
    if not holdings:
        return []

    tickers = list({h.ticker for h in holdings})
    prices  = _fetch_current_prices(tickers)

    # Fetch all sell records for these holdings in one query
    holding_ids = [h.id for h in holdings]
    sells = (
        db.query(PortfolioSell)
        .filter(PortfolioSell.holding_id.in_(holding_ids))
        .order_by(PortfolioSell.sell_date.asc())
        .all()
    )
    sells_by_holding: dict[int, list] = {}
    for s in sells:
        sells_by_holding.setdefault(s.holding_id, []).append(s)

    result = []
    for h in holdings:
        cp        = prices.get(h.ticker)
        h_sells   = sells_by_holding.get(h.id, [])
        sold_shares = sum(s.shares_sold for s in h_sells)
        remaining   = max(h.shares - sold_shares, 0)

        cost      = round(h.shares * h.buy_price, 2)
        value     = round(remaining * cp, 2) if cp else None
        pnl       = round(value - remaining * h.buy_price, 2) if value is not None else None
        pnl_p     = round(pnl / (remaining * h.buy_price) * 100, 2) if (pnl is not None and remaining > 0) else None

        # Realized P&L from sold shares
        realized  = round(sum((s.sell_price - h.buy_price) * s.shares_sold for s in h_sells), 2)

        result.append({
            "id":              h.id,
            "ticker":          h.ticker,
            "shares":          h.shares,
            "shares_remaining": round(remaining, 4),
            "shares_sold":     round(sold_shares, 4),
            "buy_price":       h.buy_price,
            "buy_date":        h.buy_date,
            "notes":           h.notes,
            "current_price":   round(cp, 2) if cp else None,
            "cost_basis":      cost,
            "current_value":   value,
            "pnl":             pnl,
            "pnl_pct":         pnl_p,
            "realized_pnl":    realized if h_sells else None,
            "sells":           [
                {
                    "id":          s.id,
                    "shares_sold": s.shares_sold,
                    "sell_price":  s.sell_price,
                    "sell_date":   s.sell_date,
                    "notes":       s.notes,
                    "realized_pnl": round((s.sell_price - h.buy_price) * s.shares_sold, 2),
                }
                for s in h_sells
            ],
        })
    return result


@router.post("/portfolio", tags=["portfolio"], status_code=201)
def add_holding(payload: AddHoldingRequest, db: Session = Depends(get_db)):
    """Add a manually bought position to the portfolio."""
    h = PortfolioHolding(
        ticker    = payload.ticker.upper().strip(),
        shares    = payload.shares,
        buy_price = payload.buy_price,
        buy_date  = payload.buy_date,
        notes     = payload.notes,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return {"id": h.id, "ticker": h.ticker, "message": "Position added."}


@router.get("/portfolio/sell-signals", tags=["portfolio"])
def portfolio_sell_signals(db: Session = Depends(get_db)):
    """Use Claude to recommend hold / partial-sell / sell for each position."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY not configured.")

    holdings = (
        db.query(PortfolioHolding)
        .order_by(PortfolioHolding.added_at.asc())
        .all()
    )
    if not holdings:
        return []

    tickers = list({h.ticker for h in holdings})
    prices  = _fetch_current_prices(tickers)

    # Pull last-run scores for richer context
    last = state.get_result()
    scores_map: dict = {}
    if last:
        for s in last.get("top_30", []):
            scores_map[s["ticker"]] = s

    positions = []
    for h in holdings:
        cp = prices.get(h.ticker)
        if not cp:
            continue
        cost    = h.shares * h.buy_price
        value   = h.shares * cp
        pnl_pct = round((value - cost) / cost * 100, 1)
        sc      = scores_map.get(h.ticker, {})
        positions.append({
            "ticker":          h.ticker,
            "buy_price":       round(h.buy_price, 2),
            "current_price":   round(cp, 2),
            "pnl_pct":         pnl_pct,
            "shares":          h.shares,
            "notes":           h.notes or "",
            "final_score":     sc.get("final_score"),
            "momentum_score":  sc.get("momentum_score"),
            "technical_score": sc.get("technical_score"),
            "sentiment_score": sc.get("sentiment_score"),
            "explanation":     (sc.get("explanation") or "")[:120],
        })

    if not positions:
        return []

    return _claude_sell_advice(positions)


def _claude_sell_advice(positions: list[dict]) -> list[dict]:
    import json as _j
    import re as _re
    import anthropic

    lines = []
    for i, p in enumerate(positions, 1):
        line = (
            f"{i}. {p['ticker']}: bought @${p['buy_price']}, now @${p['current_price']} "
            f"({'+' if p['pnl_pct'] >= 0 else ''}{p['pnl_pct']}%)"
        )
        if p["final_score"] is not None:
            line += (
                f" | signal {p['final_score']:.2f}/1.0"
                f" (mom {p['momentum_score']:.2f},"
                f" tech {p['technical_score']:.2f},"
                f" sent {p['sentiment_score']:.2f})"
            )
        if p["explanation"]:
            line += f". {p['explanation']}"
        lines.append(line)

    prompt = (
        "I hold these stock positions. For each give a sell recommendation.\n\n"
        + "\n".join(lines)
        + "\n\nReturn a JSON array (same order, one object per position):\n"
        '[{"ticker":"...","action":"sell"|"partial_sell"|"hold",'
        '"urgency":"high"|"medium"|"low",'
        '"reason":"<1-2 sentences>",'
        '"target_exit":"<price or condition, e.g. $185 or drops below MA50>"}]'
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=700,
            system=[{
                "type": "text",
                "text": (
                    "You are a portfolio risk manager. Given stock positions with P&L% and "
                    "multi-agent signal scores (0=very weak, 1=very strong), recommend when to sell. "
                    "Consider profit-taking at large gains, cutting losses on weak signals, "
                    "holding strong momentum. Return ONLY a valid JSON array, no extra text."
                ),
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )
        content = resp.content[0].text.strip()
        if content.startswith("```"):
            content = _re.sub(r"^```[a-z]*\n?", "", content)
            content = _re.sub(r"\n?```$", "", content.rstrip())
        return _j.loads(content)
    except Exception as exc:
        logger.warning(f"Claude sell advice failed: {exc}")
        return [
            {"ticker": p["ticker"], "action": "error", "urgency": "low",
             "reason": str(exc), "target_exit": ""}
            for p in positions
        ]


@router.post("/portfolio/{holding_id}/sells", tags=["portfolio"], status_code=201)
def record_sell(holding_id: int, payload: RecordSellRequest, db: Session = Depends(get_db)):
    """Record a partial or full sell for a holding."""
    h = db.query(PortfolioHolding).filter(PortfolioHolding.id == holding_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Holding not found.")

    existing_sold = (
        db.query(PortfolioSell)
        .filter(PortfolioSell.holding_id == holding_id)
        .all()
    )
    total_sold = sum(s.shares_sold for s in existing_sold) + payload.shares_sold
    if total_sold > h.shares:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot sell {payload.shares_sold} shares — only {h.shares - (total_sold - payload.shares_sold):.4f} remaining.",
        )

    s = PortfolioSell(
        holding_id  = holding_id,
        shares_sold = payload.shares_sold,
        sell_price  = payload.sell_price,
        sell_date   = payload.sell_date,
        notes       = payload.notes,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    realized = round((payload.sell_price - h.buy_price) * payload.shares_sold, 2)
    return {"id": s.id, "realized_pnl": realized, "message": "Sell recorded."}


@router.delete("/portfolio/sells/{sell_id}", tags=["portfolio"])
def delete_sell(sell_id: int, db: Session = Depends(get_db)):
    """Remove a sell record."""
    s = db.query(PortfolioSell).filter(PortfolioSell.id == sell_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Sell record not found.")
    db.delete(s)
    db.commit()
    return {"message": f"Sell record {sell_id} removed."}


@router.delete("/portfolio/{holding_id}", tags=["portfolio"])
def delete_holding(holding_id: int, db: Session = Depends(get_db)):
    """Remove a holding from the portfolio."""
    h = db.query(PortfolioHolding).filter(PortfolioHolding.id == holding_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Holding not found.")
    db.delete(h)
    db.commit()
    return {"message": f"Holding {holding_id} removed."}


def _fetch_current_prices(tickers: list[str]) -> dict[str, float | None]:
    import yfinance as yf
    if not tickers:
        return {}
    try:
        raw = yf.download(
            tickers if len(tickers) > 1 else tickers[0],
            period="2d", progress=False, auto_adjust=True,
        )
        close = raw["Close"] if "Close" in raw else raw
        out: dict[str, float | None] = {}
        for t in tickers:
            try:
                series = close[t] if len(tickers) > 1 else close
                out[t] = float(series.dropna().iloc[-1])
            except Exception:
                out[t] = None
        return out
    except Exception:
        return {t: None for t in tickers}


# ── Price prediction ──────────────────────────────────────────────────────

@router.get("/predict/{ticker}", tags=["predictions"])
def predict_stock(ticker: str, months: int = 4):
    """Return a multi-month price forecast for a ticker (linear regression + ATR bands)."""
    from agents.prediction_agent import PredictionAgent
    months = max(1, min(6, months))
    result = PredictionAgent().predict(ticker.upper(), months=months)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ── Industry performance ──────────────────────────────────────────────────────

_INDPERF_CACHE: dict[int, dict] = {}  # days -> {"ts": float, "data": list}
_INDPERF_TTL   = 3_600               # 1 hour per days-bucket

@router.get("/industry-performance", tags=["rankings"])
def industry_performance(days: int = 20):
    """Return per-industry avg % change over the last N trading days."""
    import time
    from utils.sectors import SECTOR_COLORS, get_sector_info
    from config import STOCK_UNIVERSE

    now    = time.time()
    bucket = _INDPERF_CACHE.get(days)
    if bucket and (now - bucket["ts"]) < _INDPERF_TTL:
        return bucket["data"]

    tickers = [t for t in STOCK_UNIVERSE if t not in ("SPY", "QQQ")]

    import yfinance as yf
    try:
        raw   = yf.download(tickers, period="1mo", progress=False, auto_adjust=True)
        close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
    except Exception as exc:
        logger.warning(f"industry-performance download failed: {exc}")
        return []

    buckets: dict[str, dict] = {}
    for ticker in tickers:
        info     = get_sector_info(ticker)
        sector   = info["sector"]
        industry = info["industry"]
        if sector == "ETF":
            continue
        try:
            series = close[ticker] if ticker in close.columns else close
            series = series.dropna()
            if len(series) < 5:
                continue
            window  = series.iloc[-min(days, len(series)):]
            pct_chg = float((window.iloc[-1] - window.iloc[0]) / window.iloc[0] * 100)
        except Exception:
            continue

        if industry not in buckets:
            buckets[industry] = {
                "industry":    industry,
                "sector":      sector,
                "color":       SECTOR_COLORS.get(sector, "#64748b"),
                "changes":     [],
                "tickers":     [],
            }
        buckets[industry]["changes"].append(pct_chg)
        buckets[industry]["tickers"].append(ticker)

    result = []
    for data in buckets.values():
        changes = data.pop("changes")
        data["avg_change_pct"]  = round(sum(changes) / len(changes), 2)
        data["best_ticker"]     = data["tickers"][changes.index(max(changes))]
        data["best_change_pct"] = round(max(changes), 2)
        data["stock_count"]     = len(data["tickers"])
        result.append(data)

    result.sort(key=lambda x: x["avg_change_pct"], reverse=True)
    _INDPERF_CACHE[days] = {"ts": now, "data": result}
    return result


# ── Buy analysis ─────────────────────────────────────────────────────────────

@router.get("/buy-analysis/{ticker}", tags=["signals"])
def buy_analysis(ticker: str, db: Session = Depends(get_db)):
    """Claude buy / wait / avoid recommendation for a ticker."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY not configured.")

    ticker = ticker.upper()

    # Prefer in-memory state (freshest data)
    last = state.get_result()
    stock = None
    if last:
        stock = next((s for s in last["top_30"] if s["ticker"] == ticker), None)

    if not stock:
        row = (
            db.query(RankingModel)
            .filter(RankingModel.ticker == ticker)
            .order_by(RankingModel.timestamp.desc())
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"No data for {ticker}. Run analysis first.")
        stock = _row_to_dict(row)

    # Get 3-month forecast for context
    from agents.prediction_agent import PredictionAgent
    pred = PredictionAgent().predict(ticker, months=3)

    return _claude_buy_analysis(ticker, stock, pred)


def _claude_buy_analysis(ticker: str, stock: dict, pred: dict) -> dict:
    import json as _j
    import re as _re
    import anthropic

    details  = stock.get("details") or {}
    mom      = details.get("momentum")  or {}
    tech     = details.get("technical") or {}
    vol      = details.get("volume")    or {}
    vwap     = details.get("vwap")      or {}
    brk      = details.get("breakout")  or {}
    sent     = details.get("sentiment") or {}

    cp       = stock.get("curr_close") or mom.get("curr_close", 0)
    rsi      = tech.get("rsi")
    rvol     = vol.get("rvol")
    above_ma = tech.get("above_ma50")
    ab_vwap  = vwap.get("above_vwap")
    breakout = brk.get("signal", "")
    cats     = sent.get("catalysts", [])
    day_chg  = mom.get("price_change_pct")

    tgt      = pred.get("targets", {}) if "error" not in pred else {}
    ind      = pred.get("indicators", {}) if "error" not in pred else {}

    lines = [
        f"Stock: {ticker}  |  Current price: ${cp:.2f}",
        f"Day change: {'+' if (day_chg or 0) >= 0 else ''}{day_chg:.2f}%" if day_chg is not None else "",
        "",
        "── Signal scores (0–1 scale) ──",
        f"Overall:    {stock['final_score']:.3f}",
        f"Momentum:   {stock['momentum_score']:.3f}",
        f"Volume:     {stock['volume_score']:.3f}  (RVOL {rvol:.1f}x)" if rvol else f"Volume:     {stock['volume_score']:.3f}",
        f"Technical:  {stock['technical_score']:.3f}  (RSI {rsi:.0f})" if rsi else f"Technical:  {stock['technical_score']:.3f}",
        f"VWAP:       {stock['vwap_score']:.3f}  ({'above' if ab_vwap else 'below'} VWAP)" if ab_vwap is not None else f"VWAP:       {stock['vwap_score']:.3f}",
        f"Breakout:   {stock['breakout_score']:.3f}  ({breakout})" if breakout else f"Breakout:   {stock['breakout_score']:.3f}",
        f"Sentiment:  {stock['sentiment_score']:.3f}  catalysts: {', '.join(cats[:3])}" if cats else f"Sentiment:  {stock['sentiment_score']:.3f}",
        f"SmartMoney: {stock['smart_money_score']:.3f}",
        f"Above MA50: {above_ma}" if above_ma is not None else "",
        "",
        "── 3-month statistical forecast ──",
        f"Base target: ${tgt.get('base', 0):.2f}  Bull: ${tgt.get('bull', 0):.2f}  Bear: ${tgt.get('bear', 0):.2f}" if tgt else "Forecast unavailable",
        f"Trend: {ind.get('trend', '')}  ({ind.get('slope_pct_per_month', 0):+.2f}%/month)" if ind else "",
        f"MA50: ${ind.get('ma50', 0):.2f}  MA200: ${ind.get('ma200', 0):.2f}" if ind else "",
        "",
        stock.get("explanation", ""),
    ]
    prompt = "\n".join(l for l in lines if l is not None)
    prompt += (
        "\n\nGiven the above, should I buy this stock now? Return JSON:\n"
        '{"recommendation":"buy"|"wait"|"avoid",'
        '"confidence":"high"|"medium"|"low",'
        '"entry_price":<ideal entry price as float>,'
        '"stop_loss":<stop loss price as float>,'
        '"target_price":<price target as float>,'
        '"risk_reward":<risk/reward ratio as float>,'
        '"reasoning":"<2-3 sentences>",'
        '"risks":["<risk1>","<risk2>"]}'
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=500,
            system=[{
                "type": "text",
                "text": (
                    "You are a professional stock trader and risk manager. "
                    "Given multi-agent signal scores, technical indicators, and a price forecast, "
                    "give a clear buy/wait/avoid recommendation with entry, stop loss, and target. "
                    "Be direct and specific. Return ONLY valid JSON, no extra text."
                ),
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )
        content = resp.content[0].text.strip()
        if content.startswith("```"):
            content = _re.sub(r"^```[a-z]*\n?", "", content)
            content = _re.sub(r"\n?```$", "", content.rstrip())
        return _j.loads(content)
    except Exception as exc:
        logger.warning(f"Claude buy analysis failed for {ticker}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_dict(r: RankingModel) -> dict:
    import json as _json
    return {
        "ticker":           r.ticker,
        "rank":             r.rank,
        "curr_close":       r.curr_close,
        "final_score":      r.final_score,
        "momentum_score":   r.momentum_score,
        "volume_score":     r.volume_score,
        "technical_score":  r.technical_score,
        "vwap_score":       r.vwap_score,
        "breakout_score":   r.breakout_score,
        "sentiment_score":  r.sentiment_score,
        "smart_money_score": r.smart_money_score,
        "explanation":      r.explanation,
        "details":          _json.loads(r.details) if r.details else {},
        "timestamp":        r.timestamp.isoformat() if r.timestamp else None,
        "run_id":           r.run_id,
    }


def _weight(agent: str) -> float:
    from config import WEIGHTS
    return WEIGHTS.get(agent, 0.0)
