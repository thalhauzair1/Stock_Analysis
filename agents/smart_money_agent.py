"""
Smart Money Agent — 100 % free, no API key required.

Data sources
────────────
• SEC EDGAR Form 4 (insider trades) — official REST API, no auth needed.
  Parses each filing's XML to find transaction code "P" (open-market purchase),
  so only real buys count, not grants / automatic-sales-plan dispositions.

Congress trading data (House/Senate Stock Watcher) was a popular free source
but those S3 buckets were taken offline in 2025.  The agent logs a debug note
and falls back to EDGAR-only scoring, which is more actionable anyway.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from agents.base_agent import BaseAgent

# ── SEC EDGAR endpoints ───────────────────────────────────────────────────────
_SEC_TICKERS_URL     = "https://www.sec.gov/files/company_tickers.json"
_SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_SEC_FILING_URL      = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

# SEC Fair-use: identify yourself, max ~10 req/s
_SEC_HEADERS = {"User-Agent": "StockIntelligenceMVP contact@example.com"}

_CIK_CACHE_TTL  = 24 * 3600   # refresh CIK map once a day
_MAX_FORM4_PARSE = 8           # cap XML downloads per ticker


class SmartMoneyAgent(BaseAgent):
    name = "smart_money"

    # ── Class-level cache shared across all instances ─────────────────────────
    _cik_map:    Optional[dict[str, int]] = None
    _cik_loaded: float = 0.0

    # ── Entry point ───────────────────────────────────────────────────────────

    def analyze(self, ticker: str, market_data: dict) -> dict:
        buy_count = self._insider_buys(ticker)

        # Score: 0 buys → 0, 1 buy → ~0.30, 2 buys → ~0.52, 3+ → ~0.65+
        score = 0.0
        for i in range(min(buy_count, 5)):
            score += 0.30 * (0.85 ** i)   # diminishing returns per additional buyer
        score = min(score, 1.0)

        return {
            "score": score,
            "details": {
                "insider_buys":        buy_count,
                "politician_buys":     0,          # Congress watchers offline
                "recent_insider_trades": [],
                "source": "sec_edgar_form4",
                "note": (
                    "Congress trading data (House/Senate Stock Watcher) is offline. "
                    "Score reflects SEC Form 4 open-market purchases only."
                    if buy_count == 0 else
                    f"{buy_count} open-market insider purchase(s) in last 90 days (SEC Form 4)."
                ),
            },
        }

    # ── EDGAR: insider buy count via Form 4 XML parsing ──────────────────────

    def _insider_buys(self, ticker: str) -> int:
        """
        Download recent Form 4 filings for *ticker* from EDGAR and count
        transactions with transactionCode == 'P' (open-market purchase).
        Returns 0 on any failure.
        """
        try:
            cik = self._get_cik(ticker)
            if cik is None:
                return 0

            subs = _fetch(
                _SEC_SUBMISSIONS_URL.format(cik=cik),
                headers=_SEC_HEADERS, timeout=8,
            )
            if not subs:
                return 0

            recent    = subs.get("filings", {}).get("recent", {})
            forms     = recent.get("form", [])
            dates     = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            docs      = recent.get("primaryDocument", [])

            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=90)
            ).strftime("%Y-%m-%d")

            # Collect recent Form 4 filings with XML primary document
            candidates: list[tuple[str, str]] = []
            for form, date, acc, doc in zip(forms, dates, accessions, docs):
                if form == "4" and date >= cutoff and str(doc).endswith(".xml"):
                    # primaryDocument may contain an XSLT subdir like "xslF345X06/file.xml"
                    # Strip it — we want the raw XML, not the HTML-rendered version
                    raw_doc = str(doc).split("/")[-1]
                    candidates.append((acc.replace("-", ""), raw_doc))
                    if len(candidates) >= _MAX_FORM4_PARSE:
                        break

            # Parse each XML for "P" purchase transaction codes
            purchase_count = 0
            for acc_fmt, doc_name in candidates:
                url = _SEC_FILING_URL.format(cik=cik, acc=acc_fmt, doc=doc_name)
                xml = _fetch_text(url, headers=_SEC_HEADERS, timeout=5)
                if xml and "<transactionCode>P</transactionCode>" in xml:
                    purchase_count += 1
                time.sleep(0.12)   # ~8 req/s — stay under SEC's 10 req/s guideline

            if purchase_count > 0:
                self.logger.info(
                    f"[smart_money] {ticker}: {purchase_count} insider buy(s) in last 90d"
                )
            return purchase_count

        except Exception as exc:
            self.logger.debug(f"[smart_money] EDGAR lookup failed for {ticker}: {exc}")
            return 0

    # ── CIK lookup ─────────────────────────────────────────────────────────────

    def _get_cik(self, ticker: str) -> Optional[int]:
        now = time.time()
        if SmartMoneyAgent._cik_map is None or (now - SmartMoneyAgent._cik_loaded) > _CIK_CACHE_TTL:
            raw = _fetch(_SEC_TICKERS_URL, headers=_SEC_HEADERS, timeout=10)
            SmartMoneyAgent._cik_map    = (
                {v["ticker"].upper(): int(v["cik_str"]) for v in raw.values()}
                if raw else {}
            )
            SmartMoneyAgent._cik_loaded = now
            self.logger.info(f"SEC CIK map loaded: {len(SmartMoneyAgent._cik_map)} tickers")
        return SmartMoneyAgent._cik_map.get(ticker.upper())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch(url: str, headers: dict | None = None, timeout: int = 10):
    try:
        r = requests.get(url, headers=headers or {}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _fetch_text(url: str, headers: dict | None = None, timeout: int = 10) -> Optional[str]:
    try:
        r = requests.get(url, headers=headers or {}, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception:
        return None
