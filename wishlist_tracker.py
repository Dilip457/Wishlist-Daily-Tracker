"""
Wishlist Stock Daily Tracker
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Architecture:

  GitHub Actions (cron: Mon–Fri 6 PM IST)
        ↓
  Data Fetch Layer:
      1. YahooFinanceProvider   (yfinance library, ticker.history — works on
                                  yfinance 0.2.x and 1.x, with retry + backoff)
      2. YahooChartAPIProvider  (direct Yahoo v8 chart REST API fallback when
                                  the yfinance library fails/rate-limits)
      3. Persistent cache       (data/cache.json — last good value per symbol)
        ↓
  Validation Layer      (price > 0, 52W high > low, etc.)
        ↓
  Opportunity Scoring   (% from 52W high/low, dip label, new 52W flags)
        ↓
  PDF Report            (single multi-page PDF via reportlab — one document
                          instead of multiple images, far easier to read)
        ↓
  Telegram Delivery     (sendDocument to group/channel)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Split layout:
  wishlist_config.py  — sector configuration + validation + scoring
  pdf_report.py       — PDF report builder (original layout + sector return)
  wishlist_tracker.py — data providers, orchestration, Telegram delivery
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime

import requests
import yfinance as yf

from wishlist_config import (IST, WISHLIST_SECTORS, validate_stock_data,
                             score_opportunity, dip_label, sector_metrics)

try:
    from pdf_report import build_pdf_report
    PDF_REPORT_AVAILABLE = True
except Exception:
    PDF_REPORT_AVAILABLE = False
    print("WARNING: reportlab not installed — falling back to text messages.")

# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — DATA PROVIDERS (primary + fallback + cache)
# ═══════════════════════════════════════════════════════════════════════════════

class MarketDataProvider(ABC):
    """Abstract base class for market data providers."""

    @abstractmethod
    def get_stock_data(self, symbol: str) -> dict:
        """Fetch data for a single NSE symbol. Returns a StockData dict."""

    def get_all_stocks(self, symbols: list[str]) -> dict[str, dict]:
        results: dict[str, dict] = {}
        for sym in symbols:
            results[sym] = self.get_stock_data(sym)
            time.sleep(0.3)   # polite delay
        return results

def _empty_stock_data(symbol: str, error: str) -> dict:
    """Return a zeroed-out StockData dict with an error message."""
    return {
        "symbol":     symbol,
        "last_price": 0.0,
        "high_52w":   0.0,
        "low_52w":    0.0,
        "day_high":   0.0,
        "day_low":    0.0,
        "p_change":   0.0,
        "prev_close": 0.0,
        "source":     "error",
        "timestamp":  datetime.now(IST).isoformat(),
        "error":      error,
    }

def _build_stock_data(symbol: str, last_price: float, prev_close: float,
                      high_52w: float, low_52w: float,
                      day_high: float, day_low: float, source: str) -> dict:
    """Assemble the normalized StockData dict shared by all providers."""
    if last_price <= 0 or high_52w <= 0 or low_52w <= 0:
        return _empty_stock_data(symbol, "invalid price data returned")
    p_change = (
        round((last_price - prev_close) / prev_close * 100, 2)
        if prev_close else 0.0
    )
    return {
        "symbol":     symbol,
        "last_price": round(last_price, 2),
        "high_52w":   round(high_52w, 2),
        "low_52w":    round(low_52w, 2),
        "day_high":   round(day_high, 2),
        "day_low":    round(day_low, 2),
        "p_change":   p_change,
        "prev_close": round(prev_close, 2),
        "source":     source,
        "timestamp":  datetime.now(IST).isoformat(),
        "error":      None,
    }

class YahooFinanceProvider(MarketDataProvider):
    """
    Primary provider — yfinance library.

    Uses ticker.history(period="1y") rather than fast_info, because the
    fast_info attributes (fifty_two_week_high, etc.) were removed or
    renamed in yfinance 1.x and returned None/nan, which silently broke
    every quote. The history() API works on both 0.2.x and 1.x.
    """

    _SUFFIX  = ".NS"
    _RETRIES = 3

    def _fetch_history(self, yf_symbol: str):
        """
        Download 1 year of daily OHLC bars, retrying on Yahoo's transient
        throttling ('possibly delisted; no price data found' is usually
        rate limiting, not a bad symbol — a retry fixes it).
        """
        last_err = "unknown error"
        for attempt in range(1, self._RETRIES + 1):
            try:
                hist = yf.Ticker(yf_symbol).history(
                    period="1y", interval="1d", auto_adjust=True,
                )
                if (hist is not None and len(hist) >= 2
                        and hist["Close"].dropna().shape[0] >= 2):
                    return hist
                last_err = "empty price history"
            except Exception as exc:
                last_err = str(exc)
            if attempt < self._RETRIES:
                time.sleep(2 ** (attempt - 1))   # 1s, 2s backoff
        print(f"  [YahooFinanceProvider] {yf_symbol}: all {self._RETRIES} "
              f"attempts failed ({last_err})")
        return None

    def get_stock_data(self, symbol: str) -> dict:
        yf_symbol = symbol + self._SUFFIX
        hist = self._fetch_history(yf_symbol)
        if hist is None:
            return _empty_stock_data(symbol, "history fetch failed after retries")
        try:
            close = hist["Close"].dropna()
            return _build_stock_data(
                symbol,
                last_price=float(close.iloc[-1]),
                prev_close=float(close.iloc[-2]),
                high_52w=float(hist["High"].max()),
                low_52w=float(hist["Low"].min()),
                day_high=float(hist["High"].iloc[-1]),
                day_low=float(hist["Low"].iloc[-1]),
                source="yahoo_finance",
            )
        except Exception as exc:
            print(f"  [YahooFinanceProvider] {symbol}: {exc}")
            return _empty_stock_data(symbol, str(exc))

class YahooChartAPIProvider(MarketDataProvider):
    """
    Fallback provider — calls Yahoo's public v8 chart REST API directly.

    Independent of the yfinance library, so it still works when a new
    yfinance release breaks its internal scraping/cookie handling.
    """

    _SUFFIX  = ".NS"
    _RETRIES = 2
    _URL     = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                "?range=1y&interval=1d")
    _HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": "application/json",
    }

    def get_stock_data(self, symbol: str) -> dict:
        url = self._URL.format(sym=requests.utils.quote(symbol + self._SUFFIX))
        last_err = "unknown error"
        for attempt in range(1, self._RETRIES + 1):
            try:
                resp = requests.get(url, headers=self._HEADERS, timeout=15)
                resp.raise_for_status()
                result = resp.json()["chart"]["result"][0]
                quote  = result["indicators"]["quote"][0]

                # Keep only bars where every field we need is present.
                bars = [
                    (c, h, l) for c, h, l in zip(
                        quote.get("close", []),
                        quote.get("high", []),
                        quote.get("low", []),
                    ) if c is not None and h is not None and l is not None
                ]
                if len(bars) < 2:
                    last_err = "no usable bars"
                else:
                    return _build_stock_data(
                        symbol,
                        last_price=bars[-1][0],
                        prev_close=bars[-2][0],
                        high_52w=max(b[1] for b in bars),
                        low_52w=min(b[2] for b in bars),
                        day_high=bars[-1][1],
                        day_low=bars[-1][2],
                        source="yahoo_chart_api",
                    )
            except Exception as exc:
                last_err = str(exc)
            if attempt < self._RETRIES:
                time.sleep(attempt * 2)
        print(f"  [YahooChartAPIProvider] {symbol}: {last_err}")
        return _empty_stock_data(symbol, last_err)

# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — CACHE
# ═══════════════════════════════════════════════════════════════════════════════

_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "cache.json"
)

def load_cache() -> dict:
    if os.path.exists(_CACHE_FILE):
        try:
            with open(_CACHE_FILE, "r") as fh:
                return json.load(fh)
        except Exception as exc:
            print(f"  [Cache] Load failed: {exc} — starting fresh.")
    return {"last_updated": None, "stocks": {}}

def save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
    try:
        with open(_CACHE_FILE, "w") as fh:
            json.dump(cache, fh, indent=2)
        print(f"  [Cache] Saved {len(cache.get('stocks', {}))} entries.")
    except Exception as exc:
        print(f"  [Cache] Save failed: {exc}")

def resolve_with_cache(symbol: str, live: dict, cache: dict) -> dict:
    """Live data if valid; otherwise the last cached value, marked 'cache'."""
    if validate_stock_data(live):
        return live
    cached = cache.get("stocks", {}).get(symbol)
    if cached and validate_stock_data(cached):
        print(f"  [Cache] Using cached data for {symbol} "
              f"(live error: {live.get('error', 'invalid')})")
        return {**cached, "source": "cache"}
    return live

def update_cache(cache: dict, quotes: dict[str, dict]) -> dict:
    ist = IST
    for sym, data in quotes.items():
        if validate_stock_data(data) and data.get("source") != "cache":
            cache["stocks"][sym] = data
    cache["last_updated"] = datetime.now(ist).isoformat()
    return cache


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — DATA FETCH ORCHESTRATION (primary -> fallback -> cache)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_all_quotes(symbols: list[str], cache: dict) -> dict[str, dict]:
    """
    Fetch every symbol with layered fallbacks:
      1. yfinance (primary, retry + backoff)
      2. Yahoo v8 chart REST API (library-independent fallback)
      3. one extra retry round for anything still failing
      4. cached value from data/cache.json (marked as cached in the report)
    """
    quotes: dict[str, dict] = {}
    providers = [YahooFinanceProvider(), YahooChartAPIProvider()]

    for sym in symbols:
        for provider in providers:
            data = provider.get_stock_data(sym)
            if validate_stock_data(data):
                quotes[sym] = data
                break
            quotes[sym] = data   # keep last error; next provider may fix it

    # ── Extra retry round for anything that failed every provider ──────────
    retry_syms = [s for s in symbols if not validate_stock_data(quotes[s])]
    if retry_syms:
        print(f"  Retrying {len(retry_syms)} failed symbol(s) after pause: "
              f"{', '.join(retry_syms)}")
        time.sleep(10)
        for sym in retry_syms:
            for provider in providers:
                data = provider.get_stock_data(sym)
                if validate_stock_data(data):
                    quotes[sym] = data
                    break

    # ── Final fallback: cache ────────────────────────────────────────────────
    for sym in symbols:
        quotes[sym] = resolve_with_cache(sym, quotes[sym], cache)

    return quotes

def build_caption(quotes: dict) -> str:
    valid = {s: q for s, q in quotes.items() if validate_stock_data(q)}
    failed = len(quotes) - len(valid)
    deep = sum(1 for q in valid.values() if abs(q["pct_from_high"]) >= 10)
    new_hi = [s for s, q in valid.items() if q.get("new_52w_high")]
    new_lo = [s for s, q in valid.items() if q.get("new_52w_low")]

    # best / worst sector by equal-weighted 1-day return
    sec_rets = []
    for sec in WISHLIST_SECTORS:
        m = sector_metrics(sec, quotes)
        if m:
            sec_rets.append((sec["sector"].title(), m["avg_day"]))
    sec_line = ""
    if len(sec_rets) >= 2:
        best = max(sec_rets, key=lambda x: x[1])
        worst = min(sec_rets, key=lambda x: x[1])
        sec_line = (f"\n📈 Best sector: {best[0]} {best[1]:+.2f}%"
                    f"  •  Worst: {worst[0]} {worst[1]:+.2f}%")

    now = datetime.now(IST)
    cap = (f"<b>Wishlist Stock Tracker — {now.strftime('%a, %d %b %Y')}</b>\n"
           f"Live {len(valid)}/{len(quotes)}"
           + (f" • {failed} unavailable" if failed else "")
           + f" • {deep} in dip zone (10%+ below 52W high)"
           + sec_line)
    if new_hi:
        cap += f"\n🔥 New 52W high: {', '.join(sorted(new_hi))}"
    if new_lo:
        cap += f"\n🧊 New 52W low: {', '.join(sorted(new_lo))}"
    return cap

def build_text_message(quotes: dict) -> str:
    """Plain-text fallback for when reportlab is unavailable."""
    now = datetime.now(IST)
    date_str = now.strftime("%d %b %Y  |  %I:%M %p IST")

    lines = ["=" * 52,
             f"  WISHLIST STOCK TRACKER  —  {date_str}",
             "=" * 52]

    for sec in WISHLIST_SECTORS:
        lines.append(f"\n{sec['sector']}")
        lines.append("-" * 40)
        for stk in sec["stocks"]:
            sym, note = stk["symbol"], stk.get("note", "")
            q = quotes.get(sym, {})
            if not validate_stock_data(q):
                src = q.get("source", "error")
                lines.append(f"  {sym}: "
                             f"{'CACHED' if src == 'cache' else 'UNAVAILABLE'}")
                continue
            pfh = q["pct_from_high"]
            flag = (" [NEW 52W HIGH!]" if q["new_52w_high"] else
                    " [NEW 52W LOW!]"  if q["new_52w_low"]  else "")
            ns = f" [{note}]" if note else ""
            lines.append(
                f"  {sym}{ns}: ₹{q['last_price']:,.2f} | "
                f"52wH ₹{q['high_52w']:,.2f} ({pfh:+.2f}% {dip_label(pfh)}) | "
                f"52wL ₹{q['low_52w']:,.2f} | Day {q['p_change']:+.2f}%{flag}"
            )

    lines += ["\n" + "=" * 52,
              "Data via Yahoo Finance (NSE). Not financial advice.",
              "=" * 52]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 7 — TELEGRAM DELIVERY
# ═══════════════════════════════════════════════════════════════════════════════

def _send_document(bot_token: str, chat_id: str,
                   pdf_bytes: bytes, caption: str, filename: str) -> bool:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendDocument",
            data={"chat_id": chat_id, "caption": caption,
                  "parse_mode": "HTML"},
            files={"document": (filename, pdf_bytes, "application/pdf")},
            timeout=90,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        print(f"  [Telegram] sendDocument to {chat_id} failed: {exc}")
        return False

def _send_message(bot_token: str, chat_id: str, text: str) -> bool:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=30,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        print(f"  [Telegram] sendMessage to {chat_id} failed: {exc}")
        return False

def notify_all(bot_token: str, chat_ids_str: str,
               pdf_bytes: bytes | None, filename: str,
               caption: str, text_msg: str) -> None:
    chat_ids = [c.strip() for c in chat_ids_str.split(",") if c.strip()]
    for chat_id in chat_ids:
        print(f"  Sending to {chat_id}...")
        if pdf_bytes and PDF_REPORT_AVAILABLE:
            ok = _send_document(bot_token, chat_id, pdf_bytes, caption, filename)
            if not ok:
                _send_message(bot_token, chat_id, text_msg)
        else:
            _send_message(bot_token, chat_id, text_msg)
        time.sleep(2)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def get_unique_symbols() -> list[str]:
    """Deduplicated list of all NSE symbols across all sectors."""
    seen: dict[str, bool] = {}
    for sec in WISHLIST_SECTORS:
        for stk in sec["stocks"]:
            seen[stk["symbol"]] = True
    return list(seen.keys())

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    now = datetime.now(IST)
    print(f"\n{'='*60}")
    print(f"  WISHLIST STOCK TRACKER  —  "
          f"{now.strftime('%d %b %Y  %I:%M %p IST')}")
    print(f"{'='*60}\n")

    bot_token    = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids_str = (os.environ.get("WISHLIST_TELEGRAM_CHAT_IDS", "").strip()
                    or os.environ.get("TELEGRAM_CHAT_IDS", "").strip())

    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable not set.")
    if not chat_ids_str:
        raise RuntimeError(
            "WISHLIST_TELEGRAM_CHAT_IDS not set.\n"
            "Add it in GitHub → Settings → Secrets and variables → Actions."
        )

    symbols = get_unique_symbols()
    print(f"Tracking {len(symbols)} unique symbols across "
          f"{len(WISHLIST_SECTORS)} sectors.\n")

    # ── Step 1: Load cache ────────────────────────────────────────────────────
    print("Step 1: Loading cache...")
    cache = load_cache()
    print(f"  Cache loaded: {len(cache.get('stocks', {}))} entries "
          f"(last updated: {cache.get('last_updated', 'never')})")

    # ── Step 2: Fetch live data (primary + fallback providers) ────────────────
    print("Step 2: Fetching live data...")
    raw = fetch_all_quotes(symbols, cache)
    live_ok = sum(1 for d in raw.values() if validate_stock_data(d))
    print(f"  Fetch complete: {live_ok}/{len(symbols)} symbols OK\n")

    # ── Step 3: Score ─────────────────────────────────────────────────────────
    print("Step 3: Scoring opportunities...")
    quotes = {sym: score_opportunity(d) for sym, d in raw.items()}
    for sym in symbols:
        q = quotes[sym]
        src = q.get("source", "error")
        status = (f"OK ({src})" if validate_stock_data(q)
                  else f"FAIL ({q.get('error', '?')})")
        print(f"  {sym:<14} {status}")

    # ── Step 4: Update and save cache ─────────────────────────────────────────
    print("\nStep 4: Updating cache...")
    cache = update_cache(cache, quotes)
    save_cache(cache)

    # ── Step 5: Build PDF report ──────────────────────────────────────────────
    pdf_bytes: bytes | None = None
    filename = f"wishlist_tracker_{now.strftime('%d%b%Y')}.pdf"
    if PDF_REPORT_AVAILABLE:
        print("\nStep 5: Building PDF report...")
        try:
            pdf_bytes = build_pdf_report(quotes)
            print(f"  PDF built: {len(pdf_bytes):,} bytes")
        except Exception as exc:
            print(f"  WARNING: PDF build failed: {exc}")
    else:
        print("\nStep 5: reportlab unavailable — skipping PDF.")

    # ── Step 6: Build text fallback ───────────────────────────────────────────
    text_msg = build_text_message(quotes)
    caption  = build_caption(quotes)

    # ── Step 7: Send to Telegram ──────────────────────────────────────────────
    print("\nStep 6: Sending to Telegram...")
    notify_all(bot_token, chat_ids_str, pdf_bytes, filename, caption, text_msg)
    print("\nDone!")


if __name__ == "__main__":
    main()
