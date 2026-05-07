import json as _json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from agents.base_agent import BaseAgent
from config import ANTHROPIC_API_KEY, NEWS_API_KEY, OPENAI_API_KEY

# ── Lexicons (keyword fallback) ───────────────────────────────────────────────
_POSITIVE = {
    "surge", "soar", "jump", "rally", "beat", "exceed", "record", "high",
    "growth", "strong", "bullish", "upgrade", "outperform", "buy", "positive",
    "profit", "revenue", "contract", "deal", "partner", "launch", "expand",
    "acquisition", "merger", "buyout", "dividend", "buyback", "win", "boost",
    "breakthrough", "approval", "approved", "award",
}
_NEGATIVE = {
    "fall", "drop", "plunge", "crash", "miss", "below", "weak", "bearish",
    "downgrade", "underperform", "sell", "loss", "layoff", "cut", "recall",
    "lawsuit", "fine", "penalty", "fraud", "bankruptcy", "debt", "decline",
    "warned", "warning", "investigation", "resign",
}
_CATALYSTS: dict[str, float] = {
    "earnings":    0.15,
    "revenue":     0.10,
    "ai":          0.15,
    "acquisition": 0.12,
    "merger":      0.12,
    "buyout":      0.12,
    "contract":    0.10,
    "fda":         0.12,
    "approval":    0.10,
    "partnership": 0.08,
    "buyback":     0.08,
    "dividend":    0.06,
    "ipo":         0.08,
    "guidance":    0.07,
}

_AI_CACHE:   dict[str, tuple[float, dict]] = {}  # ticker -> (ts, result) — in-memory only
_AI_CACHE_TTL   = 3_600   # 1 hour — re-analyze with Claude each run
_NEWS_CACHE_TTL = 28_800  # 8 hours — NewsAPI is rate-limited; persist to disk

import os as _os, pathlib as _pl
_CACHE_FILE = _pl.Path(__file__).parent.parent / "news_cache.json"

def _load_disk_cache() -> dict[str, dict]:
    try:
        if _CACHE_FILE.exists():
            return _json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_disk_cache(cache: dict[str, dict]) -> None:
    try:
        _CACHE_FILE.write_text(_json.dumps(cache), encoding="utf-8")
    except Exception:
        pass

_NEWS_DISK: dict[str, dict] = _load_disk_cache()  # {ticker: {ts, articles}}

_SENTIMENT_SYSTEM_PROMPT = (
    "You are a financial news sentiment analyst. "
    "Given stock news headlines, return a JSON object with:\n"
    "- \"overall\": float 0.0 (very negative) to 1.0 (very positive)\n"
    "- \"sentiments\": array of floats, one per headline (same scale)\n"
    "- \"catalysts\": array of short strings naming key events "
    "(e.g. \"earnings beat\", \"FDA approval\", \"guidance raised\")\n"
    "Financial nuance matters: "
    "\"miss but guidance raised\" is mildly positive; "
    "\"beat but outlook cut\" is mildly negative. "
    "Return ONLY valid JSON, no extra text."
)


class NewsAgent(BaseAgent):
    name = "sentiment"

    # ── Main entry point ──────────────────────────────────────────────────────

    def analyze(self, ticker: str, market_data: dict) -> dict:
        now = time.time()

        use_ai = bool(ANTHROPIC_API_KEY) or bool(OPENAI_API_KEY)
        if use_ai:
            cached = _AI_CACHE.get(ticker)
            if cached and (now - cached[0]) < _AI_CACHE_TTL:
                return cached[1]

        articles = self._fetch(ticker)
        if not articles:
            return {"score": 0.5, "details": {"note": "no news — neutral score", "count": 0, "using_ai": False}}

        # Claude takes priority over OpenAI
        if ANTHROPIC_API_KEY:
            result = self._analyze_claude(ticker, articles)
            if result is not None:
                _AI_CACHE[ticker] = (now, result)
                return result
            self.logger.warning(f"[sentiment] Claude failed for {ticker} — falling back to keywords")
        elif OPENAI_API_KEY:
            result = self._analyze_openai(ticker, articles)
            if result is not None:
                _AI_CACHE[ticker] = (now, result)
                return result
            self.logger.warning(f"[sentiment] OpenAI failed for {ticker} — falling back to keywords")

        return self._analyze_keywords(articles)

    # ── Claude path ───────────────────────────────────────────────────────────

    def _analyze_claude(self, ticker: str, articles: list[dict]) -> Optional[dict]:
        headlines = self._format_headlines(articles)
        raw = self._claude_call(ticker, headlines)
        if raw is None:
            return None

        overall   = float(raw.get("overall", 0.5))
        catalysts = [str(c) for c in raw.get("catalysts", [])][:6]

        return {
            "score": round(max(0.0, min(overall, 1.0)), 3),
            "details": {
                "article_count":    len(articles),
                "avg_sentiment":    round(overall, 3),
                "catalysts":        catalysts,
                "top_headline":     articles[0].get("title", "") if articles else "",
                "analysis_method":  "claude/claude-haiku-4-5",
                "using_ai":         True,
            },
        }

    def _claude_call(self, ticker: str, headlines: list[str]) -> Optional[dict]:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            prompt = "\n".join(headlines)
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=350,
                system=[
                    {
                        "type": "text",
                        "text": _SENTIMENT_SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": f"Analyze these {ticker} news headlines:\n{prompt}\nReturn JSON only.",
                    }
                ],
            )
            content = response.content[0].text.strip()
            # Strip markdown code fences if Claude wrapped the JSON
            if content.startswith("```"):
                content = re.sub(r"^```[a-z]*\n?", "", content)
                content = re.sub(r"\n?```$", "", content.rstrip())
            return _json.loads(content)
        except Exception as exc:
            self.logger.warning(f"[sentiment] Claude API error for {ticker}: {exc}")
            return None

    # ── OpenAI path (fallback) ────────────────────────────────────────────────

    def _analyze_openai(self, ticker: str, articles: list[dict]) -> Optional[dict]:
        headlines = self._format_headlines(articles)
        raw = self._openai_call(ticker, headlines)
        if raw is None:
            return None

        overall    = float(raw.get("overall", 0.5))
        catalysts  = [str(c) for c in raw.get("catalysts", [])][:6]
        model_used = raw.get("_model", "gpt-4o-mini")

        return {
            "score": round(max(0.0, min(overall, 1.0)), 3),
            "details": {
                "article_count":   len(articles),
                "avg_sentiment":   round(overall, 3),
                "catalysts":       catalysts,
                "top_headline":    articles[0].get("title", "") if articles else "",
                "analysis_method": f"openai/{model_used}",
                "using_ai":        True,
            },
        }

    def _openai_call(self, ticker: str, headlines: list[str]) -> Optional[dict]:
        try:
            prompt = "\n".join(headlines)
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": _SENTIMENT_SYSTEM_PROMPT},
                        {"role": "user",   "content": f"Analyze these {ticker} news headlines:\n{prompt}"},
                    ],
                    "temperature": 0.1,
                    "max_tokens":  350,
                    "response_format": {"type": "json_object"},
                },
                timeout=15,
            )
            resp.raise_for_status()
            body    = resp.json()
            content = body["choices"][0]["message"]["content"]
            data    = _json.loads(content)
            data["_model"] = body.get("model", "gpt-4o-mini")
            return data
        except Exception as exc:
            self.logger.warning(f"[sentiment] OpenAI API error for {ticker}: {exc}")
            return None

    # ── Keyword fallback path ─────────────────────────────────────────────────

    def _analyze_keywords(self, articles: list[dict]) -> dict:
        scores:    list[float] = []
        catalysts: list[str]   = []

        for art in articles:
            text      = f"{art.get('title', '')} {art.get('description', '')}".lower()
            sentiment = self._sentiment(text)
            cat, boost = self._catalyst(text)
            if cat:
                catalysts.append(cat)
                sentiment = min(sentiment + boost, 1.0)
            scores.append(sentiment)

        avg = sum(scores) / len(scores)
        return {
            "score": avg,
            "details": {
                "article_count":   len(articles),
                "avg_sentiment":   round(avg, 3),
                "catalysts":       list(dict.fromkeys(catalysts)),
                "top_headline":    articles[0].get("title", "") if articles else "",
                "analysis_method": "keyword_matching",
                "using_ai":        False,
            },
        }

    # ── Data fetching ─────────────────────────────────────────────────────────

    def _fetch(self, ticker: str) -> list[dict]:
        if NEWS_API_KEY:
            result = self._newsapi(ticker)
            if result:
                return result
        return self._mock(ticker)

    def _newsapi(self, ticker: str) -> list[dict]:
        now    = time.time()
        cached = _NEWS_DISK.get(ticker)

        # Return disk-cached articles if still fresh
        if cached and (now - cached["ts"]) < _NEWS_CACHE_TTL:
            self.logger.debug(f"[news] {ticker}: using cached articles ({int((now - cached['ts'])/3600)}h old)")
            return cached["articles"]

        try:
            since = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
            resp  = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q":        ticker,
                    "from":     since,
                    "sortBy":   "relevancy",
                    "language": "en",
                    "pageSize": 10,
                    "apiKey":   NEWS_API_KEY,
                },
                timeout=10,
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
            _NEWS_DISK[ticker] = {"ts": now, "articles": articles}
            _save_disk_cache(_NEWS_DISK)
            self.logger.info(f"[news] {ticker}: fetched {len(articles)} articles from NewsAPI")
            return articles
        except Exception as exc:
            self.logger.warning(f"NewsAPI error for {ticker}: {exc}")
            if cached:
                return cached["articles"]  # serve stale if API fails
            return []

    @staticmethod
    def _mock(ticker: str) -> list[dict]:
        return [
            {"title": f"{ticker} maintains steady momentum amid broader market moves", "description": ""},
            {"title": f"Analysts watch {ticker} closely as sector activity picks up",  "description": ""},
        ]

    # ── Shared helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _format_headlines(articles: list[dict]) -> list[str]:
        return [
            f"{i+1}. {art.get('title', '')}"
            + (f" — {art.get('description', '')[:80]}" if art.get("description") else "")
            for i, art in enumerate(articles[:10])
        ]

    # ── NLP helpers (keyword mode) ────────────────────────────────────────────

    @staticmethod
    def _sentiment(text: str) -> float:
        words = set(re.findall(r"\b\w+\b", text))
        pos   = len(words & _POSITIVE)
        neg   = len(words & _NEGATIVE)
        total = pos + neg
        return 0.5 if total == 0 else pos / total

    @staticmethod
    def _catalyst(text: str) -> tuple[Optional[str], float]:
        for kw, boost in _CATALYSTS.items():
            if kw in text:
                return kw, boost
        return None, 0.0
