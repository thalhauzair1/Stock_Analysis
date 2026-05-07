# Stock Intelligence — Multi-Agent System

A self-hosted stock analysis dashboard powered by 7 scoring agents, Claude AI sentiment, price prediction, and a personal portfolio tracker. Runs locally, updates every hour, and serves a live web UI.

---

## What it does

Every hour the system fetches market data for ~35 liquid stocks and runs them through 7 independent agents. Each agent scores a stock from 0–1. The scores are weighted and combined into a final ranking. The top 30 stocks are displayed in a live dashboard.

### 7 Scoring Agents

| Agent | Weight | What it measures |
|---|---|---|
| Momentum | 20% | Daily % change vs SPY relative strength |
| Volume | 20% | Relative volume vs 20-day average (RVOL) |
| Technical | 15% | RSI(14) + position above/below MA50 |
| Breakout | 15% | 20-day high breakout with volume confirmation |
| VWAP | 10% | Price position vs intraday VWAP |
| Sentiment | 10% | News headline sentiment (Claude AI or keyword fallback) |
| Smart Money | 10% | Insider trades + congressional disclosures |

---

## Dashboard features

- **Top Picks** — stock cards rated Strong Buy / Buy / Watch with score bars, RSI, RVOL, and industry tag
- **Sector Heatmap** — color-coded tiles showing which sectors are up/down today
- **Industry Performance** — collapsible panel, toggle 10d / 20d / 1mo returns per industry
- **Full Rankings Table** — sortable table with all 7 agent scores, RSI, RVOL, sector/industry column
- **Price Prediction** — click any stock → 3–4 month forecast chart (linear regression + ATR confidence bands) with Claude's price target range overlaid as a purple band
- **🤖 Should I Buy?** — Claude reads all 7 scores + the forecast and returns an entry price, stop loss, target, and risk/reward ratio
- **My Portfolio** — track positions with live P&L, record partial sells with dates, see realized vs unrealized P&L
- **🤖 Sell Signals** — Claude reviews all holdings and recommends Hold / Partial Sell / Sell with exit conditions
- **Claude Sentiment** — headlines analyzed by Claude Haiku with prompt caching across all 30+ ticker calls per run

---

## Screenshots

> Add screenshots here

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, APScheduler, SQLAlchemy |
| Database | SQLite (zero config) |
| Market data | yfinance — free, no key needed |
| AI | Anthropic Claude Haiku (optional) |
| News | NewsAPI (optional, free tier) |
| Smart money | Quiver Quant API (optional) |
| Frontend | Plain HTML/CSS/JS + Chart.js 4.4 |

---

## Quick start

**1. Clone and install**

```bash
git clone https://github.com/thalhauzair1/Stock_Analysis.git
cd Stock_Analysis
pip install -r requirements.txt
```

**2. Create a `.env` file**

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

```env
# All keys are optional — the system runs without any of them

# Claude AI — enables AI sentiment, buy analysis, sell signals, price prediction commentary
ANTHROPIC_API_KEY=sk-ant-...

# NewsAPI — newsapi.org free tier (100 req/day). Articles cached 8h to disk.
NEWS_API_KEY=your_key_here

# Quiver Quant — insider + congressional trade data
QUIVER_API_KEY=your_key_here

# OpenAI — fallback sentiment if no Anthropic key
OPENAI_API_KEY=sk-...

# How often to re-run analysis (default: 1 hour)
RUN_INTERVAL_HOURS=1
```

**3. Run**

```bash
python main.py
```

Open **http://localhost:8000** — it redirects to the dashboard automatically. The first analysis starts on launch. Click **▶ Run Now** to trigger one immediately.

---

## Project structure

```
├── main.py                  # FastAPI app + scheduler startup
├── orchestrator.py          # Runs all 7 agents, ranks results, saves to DB
├── config.py                # Stock universe, weights, thresholds
├── database.py              # SQLAlchemy models
├── state.py                 # In-memory latest-result store
│
├── agents/
│   ├── base_agent.py
│   ├── momentum_agent.py
│   ├── volume_agent.py
│   ├── technical_agent.py
│   ├── vwap_agent.py
│   ├── breakout_agent.py
│   ├── news_agent.py        # Claude / OpenAI / keyword sentiment + disk cache
│   ├── smart_money_agent.py
│   └── prediction_agent.py  # Linear regression + ATR bands + Claude overlay
│
├── api/
│   └── routes.py            # All REST endpoints
│
├── utils/
│   ├── logger.py
│   └── sectors.py           # Sector/industry mapping + colors
│
├── models/
│   └── schemas.py
│
├── dashboard/
│   └── index.html           # Entire frontend — single file
│
├── news_cache.json          # Auto-created — persists NewsAPI articles (8h TTL)
└── stock_intelligence.db    # Auto-created SQLite database
```

---

## REST API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Status, last run time, which API keys are active |
| GET | `/top-stocks?limit=30` | Latest ranked stocks with sector and industry |
| GET | `/sectors` | Sector performance from the latest run |
| GET | `/industry-performance?days=20` | Per-industry % return over N trading days |
| GET | `/stock/{ticker}` | Latest ranking for a single ticker |
| GET | `/signals/{ticker}` | Full per-agent signal breakdown |
| GET | `/predict/{ticker}?months=4` | Price forecast + Claude analysis |
| GET | `/buy-analysis/{ticker}` | Claude buy / wait / avoid recommendation |
| GET | `/history?limit=50` | Recent rankings across all runs |
| POST | `/run` | Trigger a full analysis run |
| GET | `/portfolio` | Holdings with live P&L and sell history |
| POST | `/portfolio` | Add a position |
| DELETE | `/portfolio/{id}` | Remove a position |
| POST | `/portfolio/{id}/sells` | Record a partial or full sell |
| DELETE | `/portfolio/sells/{id}` | Remove a sell record |
| GET | `/portfolio/sell-signals` | Claude hold/sell advice for all positions |

---

## Configuration

### Change the stock universe

Edit `STOCK_UNIVERSE` in `config.py`:

```python
STOCK_UNIVERSE = [
    "AAPL", "NVDA", "MSFT",
    "YOUR_TICKER_HERE",
]
```

Sector and industry are looked up automatically from yfinance for any ticker not already known.

### Adjust agent weights

Edit `WEIGHTS` in `config.py`. Must sum to `1.0`:

```python
WEIGHTS = {
    "momentum":    0.20,
    "volume":      0.20,
    "technical":   0.15,
    "breakout":    0.15,
    "vwap":        0.10,
    "sentiment":   0.10,
    "smart_money": 0.10,
}
```

---

## API key costs

| Service | Free tier | Typical monthly cost |
|---|---|---|
| yfinance | Unlimited | Free |
| NewsAPI | 100 req/day | Free (8h disk cache keeps usage ~30 calls/day) |
| Claude Haiku | Pay-as-you-go | ~$0.05 at 1 run/hour |
| OpenAI GPT-4o-mini | Pay-as-you-go | ~$0.05 at 1 run/hour |
| Quiver Quant | Paid plans | Depends on plan |

The system works with **zero API keys** — yfinance provides all price data and keyword matching handles sentiment. Keys unlock progressively better features.

---

## How scoring works

Each agent returns a score between `0.0` (worst) and `1.0` (best). Scores are multiplied by their weights and summed:

```
final_score = 0.20 × momentum
            + 0.20 × volume
            + 0.15 × technical
            + 0.15 × breakout
            + 0.10 × vwap
            + 0.10 × sentiment
            + 0.10 × smart_money
```

Stocks are then filtered (min price $5, min avg volume 500K, max RSI 80) and ranked by `final_score`.

---

## License

MIT
