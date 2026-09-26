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
"""

from __future__ import annotations

import io
import json
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime

import pytz
import requests
import yfinance as yf

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (Flowable, KeepTogether, PageBreak,
                                    Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("WARNING: reportlab not installed — falling back to text messages.")

IST = pytz.timezone("Asia/Kolkata")

# ══════
# STOCK CONFIGURATION
# ══════

WISHLIST_SECTORS: list[dict] = [
    {
        "sector": "ALCOHOL & BREWERIES",
        "color":  (255, 180, 50),
        "stocks": [
            {"symbol": "RADICO",      "name": "Radico Khaitan"},
        ],
    },
    {
        "sector": "POWER SECTOR",
        "color":  (88, 200, 255),
        "stocks": [
            {"symbol": "TATAPOWER",   "name": "Tata Power"},
            {"symbol": "CGPOWER",     "name": "CG Power"},
        ],
    },
    {
        "sector": "EXCHANGE PLATFORM",
        "color":  (63, 185, 80),
        "stocks": [
            {"symbol": "BSE",         "name": "BSE Ltd"},
            {"symbol": "MCX",         "name": "MCX India"},
        ],
    },
    {
        "sector": "SHRIMP SECTOR",
        "color":  (248, 81, 73),
        "stocks": [
            {"symbol": "AVANTIFEED",  "name": "Avanti Feed",  "note": "EXITING"},
        ],
    },
    {
        "sector": "AUTO SECTOR",
        "color":  (139, 92, 246),
        "stocks": [
            {"symbol": "TVSMOTOR",    "name": "TVS Motor"},
            {"symbol": "M&M",         "name": "Mahindra & Mahindra"},
        ],
    },
    {
        "sector": "FERTILIZER SECTOR",
        "color":  (34, 197, 94),
        "stocks": [
            {"symbol": "COROMANDEL",  "name": "Coromandel Int"},
        ],
    },
    {
        "sector": "CABLE SECTOR",
        "color":  (240, 136, 62),
        "stocks": [
            {"symbol": "KEI",         "name": "KEI Industries"},
        ],
    },
    {
        "sector": "HOSPITALITY SECTOR",
        "color":  (236, 72, 153),
        "stocks": [
            {"symbol": "INDHOTEL",    "name": "Indian Hotels"},
        ],
    },
    {
        "sector": "PHARMA SECTOR",
        "color":  (20, 184, 166),
        "stocks": [
            {"symbol": "TORNTPHARM",  "name": "Torrent Pharma"},
        ],
    },
    {
        "sector": "CAPITAL GOODS SECTOR",
        "color":  (255, 200, 0),
        "stocks": [
            {"symbol": "CUMMINSIND",  "name": "Cummins India"},
        ],
    },
    {
        "sector": "IT SECTOR",
        "color":  (88, 166, 255),
        "stocks": [
            {"symbol": "PERSISTENT",  "name": "Persistent Systems"},
        ],
    },
    {
        "sector": "AUTO ANCILLARY SECTOR",
        "color":  (251, 146, 60),
        "stocks": [
            {"symbol": "UNOMINDA",    "name": "Uno Minda"},
            {"symbol": "SONACOMS",    "name": "Sona Comstar"},
        ],
    },
    {
        "sector": "SEMICONDUCTOR SECTOR",
        "color":  (167, 139, 250),
        "stocks": [
            {"symbol": "MOSCHIP",     "name": "MosChip Tech",  "note": "highly valued"},
        ],
    },
    {
        "sector": "SPACE SECTOR",
        "color":  (56, 189, 248),
        "stocks": [
            {"symbol": "LT",          "name": "L&T"},
            {"symbol": "DATAPATTNS",  "name": "Data Patterns"},
        ],
    },
    {
        "sector": "DATA CENTER SECTOR",
        "color":  (250, 204, 21),
        "stocks": [
            {"symbol": "ANANTRAJ",    "name": "Anant Raj"},
            {"symbol": "NETWEB",      "name": "Netweb Tech"},
        ],
    },
    {
        "sector": "BANKING SECTOR",
        "color":  (52, 211, 153),
        "stocks": [
            {"symbol": "SBIN",        "name": "SBI"},
            {"symbol": "INDIANB",     "name": "Indian Bank"},
        ],
    },
    {
        "sector": "DEFENCE SECTOR",
        "color":  (248, 113, 113),
        "stocks": [
            {"symbol": "BEL",         "name": "BEL"},
        ],
    },
    {
        "sector": "HOSPITAL SECTOR",
        "color":  (196, 181, 253),
        "stocks": [
            {"symbol": "APOLLOHOSP",  "name": "Apollo Hospitals"},
            {"symbol": "FORTIS",      "name": "Fortis Healthcare"},
        ],
    },
    {
        "sector": "CONSUMER DURABLES",
        "color":  (125, 211, 252),
        "stocks": [
            {"symbol": "BLUESTARCO",  "name": "Blue Star"},
        ],
    },
]

# ══════
# LAYER 1 — DATA PROVIDERS (primary + fallback + cache)
# ══════

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


# ══════
# LAYER 2 — VALIDATION
# ══════

def validate_stock_data(data: dict) -> bool:
    """True only if the data is usable (no error, sane ranges)."""
    if not isinstance(data, dict) or data.get("error"):
        return False
    if data.get("last_price", 0.0) <= 0.0:
        return False
    if data.get("high_52w", 0.0) <= 0.0:
        return False
    if data.get("low_52w", 0.0) <= 0.0:
        return False
    if data.get("high_52w", 0.0) < data.get("low_52w", 0.0):
        return False
    return True


# ══════
# LAYER 3 — CACHE
# ══════

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


# ══════
# LAYER 4 — DATA FETCH ORCHESTRATION (primary -> fallback -> cache)
# ══════

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

    # ─── Extra retry round for anything that failed every provider ──────
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

    # ─── Final fallback: cache ──────
    for sym in symbols:
        quotes[sym] = resolve_with_cache(sym, quotes[sym], cache)

    return quotes


# ══════
# LAYER 5 — OPPORTUNITY SCORING ENGINE
# ══════

def score_opportunity(data: dict) -> dict:
    """Enrich a StockData dict with % from 52W high/low and new-52W flags."""
    if not validate_stock_data(data):
        return {**data, "pct_from_high": 0.0, "pct_from_low": 0.0,
                "new_52w_high": False, "new_52w_low": False}

    lp, h52, l52 = data["last_price"], data["high_52w"], data["low_52w"]

    pct_from_high = round((lp - h52) / h52 * 100, 2) if h52 else 0.0
    pct_from_low  = round((lp - l52) / l52 * 100, 2) if l52 else 0.0
    return {
        **data,
        "pct_from_high": pct_from_high,
        "pct_from_low":  pct_from_low,
        "new_52w_high":  h52 > 0 and lp >= h52 * 0.9995,
        "new_52w_low":   l52 > 0 and lp <= l52 * 1.0005,
    }


def dip_label(pct: float) -> str:
    if pct >= 0:    return "AT/NEAR PEAK"
    a = abs(pct)
    if a >= 20:     return "CRASH ZONE"
    if a >= 15:     return "DEEP DIP"
    if a >= 10:     return "MEDIUM DIP"
    if a >= 5:      return "MINOR DIP"
    return "NEAR PEAK"


# ══════
# LAYER 6 — PDF REPORT (dashboard + sector snapshot + sector detail)
# ══════

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Font setup: prefer DejaVu (has the ₹ glyph); fall back to Helvetica + "Rs.".
F, FB, RUPEE = "Helvetica", "Helvetica-Bold", "Rs."
try:
    pdfmetrics.registerFont(TTFont("DVS",  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DVSB", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
    F, FB, RUPEE = "DVS", "DVSB", "\u20B9"
except Exception:
    pass

PDF_BG_HEADER  = colors.HexColor("#1F2937")
PDF_BG_ZEBRA  = colors.HexColor("#F1F5F9")
PDF_TEXT       = colors.HexColor("#111827")
PDF_TEXT_SUB   = colors.HexColor("#6B7280")
PDF_GREEN      = colors.HexColor("#15803D")
PDF_YELLOW     = colors.HexColor("#B45309")
PDF_ORANGE     = colors.HexColor("#EA580C")
PDF_RED        = colors.HexColor("#DC2626")
PDF_GOLD       = colors.HexColor("#A16207")
PDF_CARD       = colors.HexColor("#F8FAFC")
PDF_LINE       = colors.HexColor("#E5E7EB")


def _dip_color(pct: float):
    a = abs(pct)
    if a >= 15: return PDF_RED
    if a >= 10: return PDF_ORANGE
    if a >= 5:  return PDF_YELLOW
    return PDF_GREEN


def _day_color(pct: float):
    if pct > 0: return PDF_GREEN
    if pct < 0: return PDF_RED
    return PDF_TEXT_SUB


def _rgb(t) -> colors.Color:
    return colors.Color(t[0] / 255, t[1] / 255, t[2] / 255)


def _tint(t, f=0.88) -> colors.Color:
    # darkened sector accent for header bands (white text stays readable)
    return colors.Color(t[0] / 255 * f, t[1] / 255 * f, t[2] / 255 * f)


def sector_metrics(sec: dict, quotes: dict) -> dict | None:
    """
    Equal-weighted 'sector index' metrics from the sector's member stocks:
      n        — number of stocks with valid data
      avg_day  — sector return: average day % change
      avg_dip  — average % from 52W high
    """
    vals = [quotes[s] for s in (stk["symbol"] for stk in sec["stocks"])
            if s in quotes and validate_stock_data(quotes[s])]
    if not vals:
        return None
    n = len(vals)
    return {
        "n":       n,
        "avg_day": round(sum(v["p_change"] for v in vals) / n, 2),
        "avg_dip": round(sum(v["pct_from_high"] for v in vals) / n, 2),
    }


class RangeBar(Flowable):
    """
    52-week position bar: a track from 52W low to high, filled from the low
    up to the current price (colored by dip severity), marker dot at the
    current price, tiny L/H labels underneath.
    """
    def __init__(self, low, high, price, width, color=None):
        super().__init__()
        self.low, self.high, self.price = low, high, price
        self.w = width
        self.color = color or PDF_TEXT_SUB

    def wrap(self, aw, ah):
        self.height = 16
        return (self.w, self.height)

    def draw(self):
        c = self.canv
        span = (self.high - self.low) or 1.0
        frac = max(0.02, min(0.98, (self.price - self.low) / span))
        c.setFillColor(PDF_LINE)
        c.roundRect(0, 9, self.w, 6, 3, stroke=0, fill=1)
        c.setFillColor(self.color)
        if frac > 0.035:
            c.roundRect(0, 9, self.w * frac, 6, 3, stroke=0, fill=1)
        c.setFillColor(PDF_TEXT)
        c.circle(self.w * frac, 12, 2.6, stroke=0, fill=1)
        c.setFont(F, 5.5)
        c.setFillColor(PDF_TEXT_SUB)
        c.drawString(0, 1, f"L {self.low:,.0f}")
        c.drawRightString(self.w, 1, f"H {self.high:,.0f}")


class DipDistribution(Flowable):
    """Tiny stacked bar: how the sector's stocks spread across dip bands."""
    def __init__(self, pcts, width=92, height=8):
        super().__init__()
        self.pcts = pcts
        self.w, self.h = width, height

    def wrap(self, aw, ah):
        return (self.w, self.h)

    def draw(self):
        c = self.canv
        bands = [PDF_GREEN, PDF_YELLOW, PDF_ORANGE, PDF_RED, PDF_RED]
        buckets = [0] * 5
        for p in self.pcts:
            a = abs(p)
            i = 0 if a < 5 else 1 if a < 10 else 2 if a < 15 else 3 if a < 20 else 4
            buckets[i] += 1
        n = len(self.pcts) or 1
        x = 0.0
        for i, cnt in enumerate(buckets):
            if not cnt:
                continue
            w = self.w * cnt / n
            c.setFillColor(bands[i])
            c.rect(x, 0, max(w - 0.7, 0.5), self.h, stroke=0, fill=1)
            x += w


class Bookmark(Flowable):
    """Zero-size flowable that registers a PDF outline (sidebar bookmark)."""
    def __init__(self, key, title):
        super().__init__()
        self.key, self.title = key, title

    def wrap(self, aw, ah):
        return (0, 0)

    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=0, closed=False)


def _p(name, **kw):
    kw.setdefault("fontName", F)
    kw.setdefault("fontSize", 9)
    kw.setdefault("leading", 12)
    kw.setdefault("textColor", PDF_TEXT)
    return ParagraphStyle(name, **kw)


def build_pdf_report(quotes: dict) -> bytes:
    """Build the multi-page PDF report. Returns PDF bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20, rightMargin=20, topMargin=36, bottomMargin=34,
        title="Wishlist Stock Tracker",
        author="Wishlist Daily Tracker",
    )
    now = datetime.now(IST)
    date_str = now.strftime("%d %b %Y  |  %I:%M %p IST")
    USABLE = A4[0] - 40   # 555.28 — every table below sums to <= this

    valid  = {s: q for s, q in quotes.items() if validate_stock_data(q)}
    ranked = sorted(valid, key=lambda s: valid[s]["pct_from_high"])
    deep   = [s for s in valid if abs(valid[s]["pct_from_high"]) >= 10]
    new_hi = [s for s in valid if valid[s].get("new_52w_high")]

    def _footer(canv, _doc):
        canv.saveState()
        canv.setFont(F, 7)
        canv.setFillColor(PDF_TEXT_SUB)
        canv.drawString(20, 20, "Wishlist Stock Tracker \u2014 data via Yahoo Finance (NSE). "
                                "Not financial advice.")
        canv.drawRightString(A4[0] - 20, 20, f"Page {canv.getPageNumber()}")
        canv.restoreState()

    def _top_header(canv, _doc):
        if canv.getPageNumber() == 1:
            return
        canv.saveState()
        canv.setFont(FB, 7)
        canv.setFillColor(PDF_TEXT_SUB)
        canv.drawCentredString(A4[0] / 2, A4[1] - 16,
                               f"Wishlist Stock Tracker \u2014 {date_str}")
        canv.restoreState()

    def _page(canv, d):
        _top_header(canv, d)
        _footer(canv, d)

    story: list = [
        Paragraph("WISHLIST STOCK TRACKER",
                  _p("t", fontName=FB, fontSize=19, leading=23, alignment=TA_CENTER)),
        Paragraph(f"Daily dip monitor \u2022 {date_str} \u2022 "
                  f"Live {len(valid)}/{len(quotes)}",
                  _p("sub", fontSize=9.5, leading=12, alignment=TA_CENTER,
                     textColor=PDF_TEXT_SUB)),
        Spacer(1, 14),
        Bookmark("summary", "Summary & Sector Snapshot"),
    ]

    # ─── KPI tiles ──────
    def tile(value, label, colr=PDF_TEXT):
        return [Paragraph(value, _p("tv", fontName=FB, fontSize=12.5,
                                    leading=15, textColor=colr,
                                    alignment=TA_CENTER)),
                Spacer(1, 2),
                Paragraph(label, _p("tl", fontSize=6.5, leading=8,
                                    textColor=PDF_TEXT_SUB, alignment=TA_CENTER))]

    tw = [130, 8, 130, 8, 130, 8, 130]        # 544
    tile_row = [
        tile(f"{ranked[0]}<br/>{valid[ranked[0]]['pct_from_high']:+.1f}%",
             "DEEPEST DIP", _dip_color(valid[ranked[0]]["pct_from_high"])),
        "",
        tile((", ".join(new_hi)[:24] + "\u2026") if new_hi else "\u2014",
             "NEW 52W HIGH", PDF_GOLD),
        "",
        tile(str(len(deep)), "IN DIP ZONE (10%+ BELOW HIGH)", PDF_ORANGE),
        "",
        tile(f"{len(valid)}/{len(quotes)}", "LIVE DATA", PDF_GREEN),
    ]
    tiles = Table([tile_row], colWidths=tw)
    for c in (0, 2, 4, 6):
        tiles.setStyle(TableStyle([
            ("BACKGROUND", (c, 0), (c, 0), PDF_CARD),
            ("BOX", (c, 0), (c, 0), 0.6, PDF_LINE),
        ]))
    tiles.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [tiles, Spacer(1, 16)]

    # ─── Sector snapshot: every sector at once ──────
    story.append(Paragraph("SECTOR SNAPSHOT \u2014 ALL SECTORS AT A GLANCE",
                           _p("sh", fontName=FB, fontSize=10.5, leading=13,
                              textColor=PDF_BG_HEADER)))
    story.append(Spacer(1, 5))

    def snap_header(txt, align=TA_RIGHT):
        return Paragraph(txt, _p("hh", fontName=FB, fontSize=7, leading=9,
                                 textColor=colors.white, alignment=align))

    snap_rows = [[snap_header("SECTOR", TA_LEFT), snap_header("#"),
                  snap_header("SECTOR RETURN"), snap_header("AVG % FROM HIGH"),
                  snap_header("DIP MIX")]]
    snap_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), PDF_BG_HEADER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, PDF_LINE),
        ("BOX", (0, 0), (-1, -1), 0.6, PDF_BG_HEADER),
    ]
    for i, sec in enumerate(WISHLIST_SECTORS):
        m = sector_metrics(sec, quotes)
        pcts = [quotes[s]["pct_from_high"]
                for s in (stk["symbol"] for stk in sec["stocks"])
                if s in quotes and validate_stock_data(quotes[s])]
        day_col = _day_color(m["avg_day"] if m else 0)
        snap_rows.append([
            Paragraph(sec["sector"], _p(f"sn{i}", fontName=FB, fontSize=8.5,
                         leading=10, textColor=_rgb(sec["color"]))),
            Paragraph(str(m["n"]) if m else "0",
                      _p(f"sc{i}", fontSize=8.5, alignment=TA_CENTER,
                         textColor=PDF_TEXT_SUB)),
            Paragraph(f"{m['avg_day']:+.2f}%" if m else "\u2014",
                      _p(f"sr{i}", fontName=FB, fontSize=9, alignment=TA_RIGHT,
                         textColor=day_col)),
            Paragraph(f"{m['avg_dip']:+.1f}%" if m else "\u2014",
                      _p(f"sd{i}", fontSize=9, alignment=TA_RIGHT,
                         textColor=_dip_color(m["avg_dip"] if m else 0))),
            DipDistribution(pcts),
        ])
    snap = Table(snap_rows, colWidths=[218, 30, 84, 100, 123])   # 555
    snap.setStyle(TableStyle(snap_styles))
    story += [snap, Spacer(1, 5),
              Paragraph("Sector return = equal-weighted average of the sector's stocks. "
                         "Dip mix: "
                         "<font color='#15803D'>\u25A0</font> near peak "
                         "<font color='#B45309'>\u25A0</font> minor "
                         "<font color='#EA580C'>\u25A0</font> medium "
                         "<font color='#DC2626'>\u25A0</font> deep/crash",
                         _p("lg", fontSize=6.5, leading=8,
                            textColor=PDF_TEXT_SUB)),
              PageBreak()]

    # ─── Sector detail pages ──────
    for sec in WISHLIST_SECTORS:
        m = sector_metrics(sec, quotes)
        key = "sec-" + sec["sector"].lower().replace(" ", "-").replace("&", "and")
        day_txt = f"1D RETURN {m['avg_day']:+.2f}%" if m else ""
        band = Table([[Paragraph(sec["sector"], _p("bn", fontName=FB,
                                    fontSize=11, leading=13,
                                    textColor=colors.white)),
                       Paragraph(f"{len(sec['stocks'])} stock"
                                 + ("s" if len(sec["stocks"]) > 1 else "")
                                 + ("   |   " + day_txt if day_txt else ""),
                                 _p("bc", fontSize=8, leading=10,
                                    textColor=colors.white,
                                    alignment=TA_RIGHT))]],
                     colWidths=[330, 225])          # 555
        band.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _tint(sec["color"])),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ]))

        def col_hdr(txt, align=TA_LEFT):
            return Paragraph(txt, _p("ch", fontName=FB, fontSize=6.8,
                                     leading=8, textColor=PDF_TEXT_SUB,
                                     alignment=align))

        rows = [[col_hdr("STOCK"), col_hdr("PRICE", TA_RIGHT),
                 col_hdr("DAY CHG", TA_RIGHT), col_hdr("52W POSITION"),
                 col_hdr("% FROM HIGH", TA_RIGHT)]]
        for stk in sec["stocks"]:
            s = stk["symbol"]
            q = quotes.get(s, {})
            if not validate_stock_data(q):
                src = q.get("source", "error")
                label = "CACHED DATA" if src == "cache" else "DATA UNAVAILABLE"
                colr = PDF_YELLOW if src == "cache" else PDF_RED
                rows.append([Paragraph(f"{s} \u2014 {label}",
                                      _p("er", fontName=FB, fontSize=8.5,
                                         textColor=colr))] +
                            [Paragraph("\u2014", _p("ed", alignment=TA_RIGHT))
                             for _ in range(4)])
                continue
            pfh = q["pct_from_high"]
            note = stk.get("note", "")
            sym_html = (f'<font name="{FB}" size="10.5">{s}</font>'
                        f'<br/><font size="7" color="#6B7280">{stk["name"]}')
            if note:
                ncol = "#DC2626" if note == "EXITING" else "#B45309"
                sym_html += (f' &nbsp;<font name="{FB}" size="6.5" '
                             f'color="{ncol}">[{note.upper()}]</font>')
            sym_html += "</font>"
            rows.append([
                Paragraph(sym_html, _p("sy", leading=12)),
                Paragraph(f"{RUPEE}{q['last_price']:,.2f}",
                          _p("pr", fontName=FB, fontSize=10.5, leading=12,
                             alignment=TA_RIGHT)),
                Paragraph(f"{q['p_change']:+.2f}%",
                          _p("dc", fontName=FB, fontSize=9, leading=11,
                             alignment=TA_RIGHT, textColor=_day_color(q["p_change"]))),
                RangeBar(q["low_52w"], q["high_52w"], q["last_price"], 165,
                         color=_dip_color(pfh)),
                Paragraph(f"{pfh:+.2f}%<br/>"
                          f'<font name="{F}" size="6.5" color="#6B7280">'
                          f'{dip_label(pfh)}</font>',
                          _p("dp", fontName=FB, fontSize=10.5, leading=12,
                             alignment=TA_RIGHT, textColor=_dip_color(pfh))),
            ])

        tbl = Table(rows, colWidths=[155, 90, 60, 170, 80])   # 555
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 1), (-1, -2), 0.4, PDF_LINE),
        ]))
        story += [Bookmark(key, sec["sector"]),
                  KeepTogether([band, Spacer(1, 3), tbl]), Spacer(1, 13)]

    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    buf.seek(0)
    return buf.read()


def build_caption(quotes: dict) -> str:
    valid = {s: q for s, q in quotes.items() if validate_stock_data(q)}
    failed = len(quotes) - len(valid)
    deep = sum(1 for q in valid.values() if abs(q["pct_from_high"]) >= 10)
    new_hi = [s for s, q in valid.items() if q.get("new_52w_high")]
    new_lo = [s for s, q in valid.items() if q.get("new_52w_low")]

    # best / worst sector by equal-weighted return
    sec_rets = []
    for sec in WISHLIST_SECTORS:
        m = sector_metrics(sec, quotes)
        if m:
            sec_rets.append((sec["sector"].title(), m["avg_day"]))
    sec_line = ""
    if len(sec_rets) >= 2:
        best = max(sec_rets, key=lambda x: x[1])
        worst = min(sec_rets, key=lambda x: x[1])
        sec_line = (f"\n\U0001F4C8 Best sector: {best[0]} {best[1]:+.2f}%"
                    f"  \u2022  Worst: {worst[0]} {worst[1]:+.2f}%")

    now = datetime.now(IST)
    cap = (f"<b>Wishlist Stock Tracker \u2014 {now.strftime('%a, %d %b %Y')}</b>\n"
           f"Live {len(valid)}/{len(quotes)}"
           + (f" \u2022 {failed} unavailable" if failed else "")
           + f" \u2022 {deep} in dip zone (10%+ below 52W high)"
           + sec_line)
    if new_hi:
        cap += f"\n\U0001F525 New 52W high: {', '.join(sorted(new_hi))}"
    if new_lo:
        cap += f"\n\U0001F9CA New 52W low: {', '.join(sorted(new_lo))}"
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


# ══════
# LAYER 7 — TELEGRAM DELIVERY
# ══════

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
        if pdf_bytes and REPORTLAB_AVAILABLE:
            ok = _send_document(bot_token, chat_id, pdf_bytes, caption, filename)
            if not ok:
                _send_message(bot_token, chat_id, text_msg)
        else:
            _send_message(bot_token, chat_id, text_msg)
        time.sleep(2)


# ══════
# HELPERS
# ══════

def get_unique_symbols() -> list[str]:
    """Deduplicated list of all NSE symbols across all sectors."""
    seen: dict[str, bool] = {}
    for sec in WISHLIST_SECTORS:
        for stk in sec["stocks"]:
            seen[stk["symbol"]] = True
    return list(seen.keys())


# ══════
# MAIN ORCHESTRATOR
# ══════

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

    # ─── Step 1: Load cache ──────
    print("Step 1: Loading cache...")
    cache = load_cache()
    print(f"  Cache loaded: {len(cache.get('stocks', {}))} entries "
          f"(last updated: {cache.get('last_updated', 'never')})")

    # ─── Step 2: Fetch live data (primary + fallback providers) ──────
    print("Step 2: Fetching live data...")
    raw = fetch_all_quotes(symbols, cache)
    live_ok = sum(1 for d in raw.values() if validate_stock_data(d))
    print(f"  Fetch complete: {live_ok}/{len(symbols)} symbols OK\n")

    # ─── Step 3: Score ──────
    print("Step 3: Scoring opportunities...")
    quotes = {sym: score_opportunity(d) for sym, d in raw.items()}
    for sym in symbols:
        q = quotes[sym]
        src = q.get("source", "error")
        status = (f"OK ({src})" if validate_stock_data(q)
                  else f"FAIL ({q.get('error', '?')})")
        print(f"  {sym:<14} {status}")

    # ─── Step 4: Update and save cache ──────
    print("\nStep 4: Updating cache...")
    cache = update_cache(cache, quotes)
    save_cache(cache)

    # ─── Step 5: Build PDF report ──────
    pdf_bytes: bytes | None = None
    filename = f"wishlist_tracker_{now.strftime('%d%b%Y')}.pdf"
    if REPORTLAB_AVAILABLE:
        print("\nStep 5: Building PDF report...")
        try:
            pdf_bytes = build_pdf_report(quotes)
            print(f"  PDF built: {len(pdf_bytes):,} bytes")
        except Exception as exc:
            print(f"  WARNING: PDF build failed: {exc}")
    else:
        print("\nStep 5: reportlab unavailable — skipping PDF.")

    # ─── Step 6: Build text fallback ──────
    text_msg = build_text_message(quotes)
    caption  = build_caption(quotes)

    # ─── Step 7: Send to Telegram ──────
    print("\nStep 6: Sending to Telegram...")
    notify_all(bot_token, chat_ids_str, pdf_bytes, filename, caption, text_msg)
    print("\nDone!")


if __name__ == "__main__":
    main()
