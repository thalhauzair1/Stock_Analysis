import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
NEWS_API_KEY      = os.getenv("NEWS_API_KEY", "")
QUIVER_API_KEY    = os.getenv("QUIVER_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./stock_intelligence.db")

# ── Scoring weights (must sum to 1.0) ─────────────────────────────────────────
WEIGHTS: dict[str, float] = {
    "momentum":    0.20,
    "volume":      0.20,
    "technical":   0.15,
    "vwap":        0.10,
    "breakout":    0.15,
    "sentiment":   0.10,
    "smart_money": 0.10,
}

# ── Stock universe — liquid, actively traded names ────────────────────────────
STOCK_UNIVERSE: list[str] = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
    # Semiconductors
    "AMD", "AVGO", "QCOM", "INTC", "MU", "ARM", "SMCI",
    # Software / Cloud
    "CRM", "ORCL", "SNOW", "NET", "DDOG", "ZS", "CRWD", "PLTR",
    # Fintech / Crypto-adjacent
    "COIN", "MARA", "RIOT", "MSTR", "XYZ", "PYPL", "SOFI", "HOOD",
    # Growth / Misc
    "NFLX", "SHOP", "RKLB", "IONQ", "TSM",
    # Reference ETFs (for relative-strength calculation only)
    "SPY", "QQQ",
]

# ── Filter thresholds ─────────────────────────────────────────────────────────
MIN_AVG_VOLUME    = 500_000   # Drop illiquid names
MAX_RSI_THRESHOLD = 80        # Drop extremely overbought
MIN_PRICE         = 5.0       # Drop micro-caps / penny stocks

# ── Results ───────────────────────────────────────────────────────────────────
TOP_N_RESULTS = 30

# ── Scheduler ─────────────────────────────────────────────────────────────────
RUN_INTERVAL_HOURS = int(os.getenv("RUN_INTERVAL_HOURS", "1"))

