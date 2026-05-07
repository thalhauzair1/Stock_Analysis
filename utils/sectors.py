import time

_CACHE_TTL = 86_400  # 24 hours
_SECTOR_CACHE: dict[str, tuple[float, dict]] = {}

# Known universe — instant lookup, no API call needed
_KNOWN: dict[str, dict] = {
    # Mega-cap tech
    "AAPL":  {"sector": "Technology",     "industry": "Consumer Electronics"},
    "MSFT":  {"sector": "Technology",     "industry": "Software"},
    "NVDA":  {"sector": "Technology",     "industry": "Semiconductors"},
    "GOOGL": {"sector": "Technology",     "industry": "Internet Services"},
    "META":  {"sector": "Technology",     "industry": "Social Media"},
    "AMZN":  {"sector": "Consumer",       "industry": "E-Commerce"},
    "TSLA":  {"sector": "Automotive",     "industry": "Electric Vehicles"},
    # Semiconductors
    "AMD":   {"sector": "Technology",     "industry": "Semiconductors"},
    "AVGO":  {"sector": "Technology",     "industry": "Semiconductors"},
    "QCOM":  {"sector": "Technology",     "industry": "Semiconductors"},
    "INTC":  {"sector": "Technology",     "industry": "Semiconductors"},
    "MU":    {"sector": "Technology",     "industry": "Semiconductors"},
    "ARM":   {"sector": "Technology",     "industry": "Semiconductors"},
    "SMCI":  {"sector": "Technology",     "industry": "Server Hardware"},
    "TSM":   {"sector": "Technology",     "industry": "Semiconductors"},
    # Software / Cloud
    "CRM":   {"sector": "Technology",     "industry": "CRM Software"},
    "ORCL":  {"sector": "Technology",     "industry": "Database Software"},
    "SNOW":  {"sector": "Technology",     "industry": "Cloud Data"},
    "NET":   {"sector": "Technology",     "industry": "Cloud Security"},
    "DDOG":  {"sector": "Technology",     "industry": "Cloud Monitoring"},
    "ZS":    {"sector": "Technology",     "industry": "Cybersecurity"},
    "CRWD":  {"sector": "Technology",     "industry": "Cybersecurity"},
    "PLTR":  {"sector": "Technology",     "industry": "Data Analytics"},
    "SHOP":  {"sector": "Technology",     "industry": "E-Commerce Platform"},
    # Fintech / Crypto
    "COIN":  {"sector": "Financials",     "industry": "Crypto Exchange"},
    "MARA":  {"sector": "Financials",     "industry": "Crypto Mining"},
    "RIOT":  {"sector": "Financials",     "industry": "Crypto Mining"},
    "MSTR":  {"sector": "Financials",     "industry": "Bitcoin Treasury"},
    "XYZ":   {"sector": "Financials",     "industry": "Digital Payments"},
    "PYPL":  {"sector": "Financials",     "industry": "Digital Payments"},
    "SOFI":  {"sector": "Financials",     "industry": "Digital Banking"},
    "HOOD":  {"sector": "Financials",     "industry": "Brokerage"},
    # Growth / Misc
    "NFLX":  {"sector": "Communication", "industry": "Streaming"},
    "RKLB":  {"sector": "Industrials",   "industry": "Space & Rockets"},
    "IONQ":  {"sector": "Technology",    "industry": "Quantum Computing"},
    # ETFs
    "SPY":   {"sector": "ETF",           "industry": "S&P 500"},
    "QQQ":   {"sector": "ETF",           "industry": "Nasdaq 100"},
}

# Sector → display color (used by dashboard)
SECTOR_COLORS: dict[str, str] = {
    "Technology":     "#3b82f6",
    "Financials":     "#8b5cf6",
    "Communication":  "#06b6d4",
    "Consumer":       "#f59e0b",
    "Automotive":     "#ec4899",
    "Industrials":    "#10b981",
    "Healthcare":     "#ef4444",
    "Energy":         "#f97316",
    "ETF":            "#64748b",
}


def get_sector_info(ticker: str) -> dict:
    """Return {sector, industry} — instant for known tickers, cached yfinance for others."""
    if ticker in _KNOWN:
        return _KNOWN[ticker]

    now = time.time()
    cached = _SECTOR_CACHE.get(ticker)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    try:
        import yfinance as yf
        info   = yf.Ticker(ticker).info
        result = {
            "sector":   info.get("sector", "Unknown") or "Unknown",
            "industry": info.get("industry", "Unknown") or "Unknown",
        }
    except Exception:
        result = {"sector": "Unknown", "industry": "Unknown"}

    _SECTOR_CACHE[ticker] = (now, result)
    return result
