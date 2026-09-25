"""
Wishlist Stock Daily Tracker
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Architecture (Phase 1):

  GitHub Actions (cron: Mon–Fri 6 PM IST)
        ↓
  YahooFinanceProvider  (yfinance — .NS suffix for NSE stocks)
        ↓
  Validation Layer      (price > 0, 52W high > low, etc.)
        ↓
  Normalization Layer   (standard StockData dict)
        ↓
  Cache Layer           (data/cache.json — committed back to repo)
        ↓
  Opportunity Scoring   (% from 52W high, dip label, new 52W flags)
        ↓
  Visualization Engine  (4 sector-group PNG images, ~900×900 px each)
        ↓
  Telegram Delivery     (sendPhoto to group/channel)

Provider abstraction is in place so Finnhub / AlphaVantage can be
plugged in later without a major refactor.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("WARNING: Pillow not installed — falling back to text messages.")

# ═══════════════════════════════════════════════════════════════════════════════
# STOCK CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

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
            {"symbol": "BEL",         "name": "BEL"},
            {"symbol": "DATAPATTNS",  "name": "Data Patterns"},
        ],
    },
    {
        "sector": "DRONE SECTOR",
        "color":  (74, 222, 128),
        "stocks": [
            {"symbol": "BEL",         "name": "BEL"},
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

# 4 images × 5 sectors each — compact and readable on mobile
SECTOR_GROUPS: list[dict] = [
    {
        "part":    "1 / 4",
        "label":   "Beverages | Power | Exchange | Shrimp | Auto",
        "indices": [0, 1, 2, 3, 4],
    },
    {
        "part":    "2 / 4",
        "label":   "Fertilizer | Cable | Hospitality | Pharma | Capital Goods",
        "indices": [5, 6, 7, 8, 9],
    },
    {
        "part":    "3 / 4",
        "label":   "IT | Auto Ancillary | Semiconductor | Space | Drone",
        "indices": [10, 11, 12, 13, 14],
    },
    {
        "part":    "4 / 4",
        "label":   "Data Center | Banking | Defence | Hospital | Consumer",
        "indices": [15, 16, 17, 18, 19],
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — PROVIDER ABSTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

class MarketDataProvider(ABC):
    """
    Abstract base class for market data providers.
    Implement this interface to add Finnhub, AlphaVantage, etc. in Phase 2.
    """

    @abstractmethod
    def get_stock_data(self, symbol: str) -> dict:
        """
        Fetch data for a single NSE symbol.
        Returns a normalized StockData dict (see _empty_stock_data).
        """

    def get_all_stocks(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch data for all symbols. Override for batch-optimized providers."""
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
        "timestamp":  datetime.now(pytz.timezone("Asia/Kolkata")).isoformat(),
        "error":      error,
    }


class YahooFinanceProvider(MarketDataProvider):
    """
    Phase 1 provider — uses yfinance library.
    NSE stocks are accessed with the .NS suffix (e.g. RADICO.NS).
    """

    _SUFFIX = ".NS"

    def get_stock_data(self, symbol: str) -> dict:
        yf_symbol = symbol + self._SUFFIX
        try:
            ticker = yf.Ticker(yf_symbol)
            fi     = ticker.fast_info

            def _f(val) -> float:
                try:
                    return float(val) if val is not None else 0.0
                except (TypeError, ValueError):
                    return 0.0

            last_price  = _f(fi.last_price)
            high_52w    = _f(fi.fifty_two_week_high)
            low_52w     = _f(fi.fifty_two_week_low)
            day_high    = _f(fi.day_high)
            day_low     = _f(fi.day_low)
            prev_close  = _f(fi.previous_close)

            p_change = (
                round((last_price - prev_close) / prev_close * 100, 2)
                if prev_close else 0.0
            )

            return {
                "symbol":     symbol,
                "last_price": last_price,
                "high_52w":   high_52w,
                "low_52w":    low_52w,
                "day_high":   day_high,
                "day_low":    day_low,
                "p_change":   p_change,
                "prev_close": prev_close,
                "source":     "yahoo_finance",
                "timestamp":  datetime.now(
                    pytz.timezone("Asia/Kolkata")
                ).isoformat(),
                "error":      None,
            }

        except Exception as exc:
            print(f"  [YahooFinanceProvider] {symbol}: {exc}")
            return _empty_stock_data(symbol, str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

def validate_stock_data(data: dict) -> bool:
    """
    Returns True only if the data is usable.
    Rejects: error states, zero prices, inverted 52W range.
    """
    if data.get("error"):
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


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — NORMALIZATION  (already handled inside each provider)
# ═══════════════════════════════════════════════════════════════════════════════
# Each provider returns the same StockData dict shape.
# No extra normalization step needed for Phase 1.


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — CACHE
# ═══════════════════════════════════════════════════════════════════════════════

_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "cache.json"
)


def load_cache() -> dict:
    """Load persistent cache from data/cache.json."""
    if os.path.exists(_CACHE_FILE):
        try:
            with open(_CACHE_FILE, "r") as fh:
                return json.load(fh)
        except Exception as exc:
            print(f"  [Cache] Load failed: {exc} — starting fresh.")
    return {"last_updated": None, "stocks": {}}


def save_cache(cache: dict) -> None:
    """Persist cache to data/cache.json (committed back to repo by workflow)."""
    os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
    try:
        with open(_CACHE_FILE, "w") as fh:
            json.dump(cache, fh, indent=2)
        print(f"  [Cache] Saved {len(cache.get('stocks', {}))} entries.")
    except Exception as exc:
        print(f"  [Cache] Save failed: {exc}")


def resolve_with_cache(symbol: str, live: dict, cache: dict) -> dict:
    """
    Return live data if valid; otherwise fall back to the last cached value.
    Marks the source as 'cache' so the image can show a staleness indicator.
    """
    if validate_stock_data(live):
        return live

    cached = cache.get("stocks", {}).get(symbol)
    if cached and validate_stock_data(cached):
        print(f"  [Cache] Using cached data for {symbol} "
              f"(live error: {live.get('error', 'invalid')})")
        return {**cached, "source": "cache"}

    # Nothing usable — return the error dict
    return live


def update_cache(cache: dict, quotes: dict[str, dict]) -> dict:
    """Merge validated live quotes into the cache."""
    ist = pytz.timezone("Asia/Kolkata")
    for sym, data in quotes.items():
        if validate_stock_data(data) and data.get("source") != "cache":
            cache["stocks"][sym] = data
    cache["last_updated"] = datetime.now(ist).isoformat()
    return cache


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 5 — OPPORTUNITY SCORING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def score_opportunity(data: dict) -> dict:
    """
    Enrich a StockData dict with opportunity metrics:
      pct_from_high  — % below 52W high (negative = below)
      pct_from_low   — % above 52W low  (positive = above)
      new_52w_high   — True if today's price is at/near the 52W high
      new_52w_low    — True if today's price is at/near the 52W low
    """
    if not validate_stock_data(data):
        return {**data, "pct_from_high": 0.0, "pct_from_low": 0.0,
                "new_52w_high": False, "new_52w_low": False}

    lp  = data["last_price"]
    h52 = data["high_52w"]
    l52 = data["low_52w"]

    pct_from_high = round((lp - h52) / h52 * 100, 2) if h52 else 0.0
    pct_from_low  = round((lp - l52) / l52 * 100, 2) if l52 else 0.0
    new_52w_high  = h52 > 0 and lp >= h52 * 0.9995
    new_52w_low   = l52 > 0 and lp <= l52 * 1.0005

    return {
        **data,
        "pct_from_high": pct_from_high,
        "pct_from_low":  pct_from_low,
        "new_52w_high":  new_52w_high,
        "new_52w_low":   new_52w_low,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 6 — VISUALIZATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

# ── Palette ───────────────────────────────────────────────────────────────────
C_BG      = (13,  17,  23)
C_CARD    = (22,  27,  34)
C_CARD2   = (30,  37,  46)
C_BORDER  = (48,  54,  61)
C_TEXT    = (230, 237, 243)
C_SUBTEXT = (139, 148, 158)
C_GREEN   = (63,  185, 80)
C_YELLOW  = (210, 153, 34)
C_ORANGE  = (240, 136, 62)
C_RED     = (248, 81,  73)
C_BLUE    = (88,  166, 255)
C_GOLD    = (255, 200, 0)
C_PURPLE  = (167, 139, 250)

IMG_W = 900
PAD   = 20

COL_X = {
    "stock":    PAD,
    "price":    PAD + 175,
    "high52w":  PAD + 295,
    "pct_high": PAD + 415,
    "low52w":   PAD + 540,
    "day_chg":  PAD + 660,
    "flag":     PAD + 770,
}
COL_W = {
    "stock":    175,
    "price":    120,
    "high52w":  120,
    "pct_high": 125,
    "low52w":   120,
    "day_chg":  110,
    "flag":     110,
}

H_HEADER     = 95
H_COL_HEADER = 30
H_SECTOR_BAR = 42
H_STOCK_ROW  = 50
H_SECTOR_GAP = 8
H_FOOTER     = 60

COL_LABELS = [
    ("stock",    "STOCK"),
    ("price",    "PRICE"),
    ("high52w",  "52W HIGH"),
    ("pct_high", "% FROM HIGH"),
    ("low52w",   "52W LOW"),
    ("day_chg",  "DAY CHG%"),
    ("flag",     "52W FLAG"),
]


def _find_font(size: int, bold: bool = False):
    if not PIL_AVAILABLE:
        return None
    bold_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
    ]
    reg_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]
    for path in (bold_paths if bold else reg_paths):
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _tw(draw, text: str, font) -> int:
    try:
        b = draw.textbbox((0, 0), text, font=font)
        return b[2] - b[0]
    except Exception:
        return len(text) * 8


def _center(draw, x, y, w, text, font, color) -> None:
    draw.text((x + (w - _tw(draw, text, font)) // 2, y),
              text, font=font, fill=color)


def _right(draw, x, y, w, text, font, color) -> None:
    draw.text((x + w - _tw(draw, text, font) - 4, y),
              text, font=font, fill=color)


def _dip_color(pct: float) -> tuple:
    a = abs(pct)
    if a >= 15: return C_RED
    if a >= 10: return C_ORANGE
    if a >= 5:  return C_YELLOW
    return C_GREEN


def _dip_label(pct: float) -> str:
    if pct >= 0:    return "AT/NEAR PEAK"
    a = abs(pct)
    if a >= 20:     return "CRASH ZONE"
    if a >= 15:     return "DEEP DIP"
    if a >= 10:     return "MEDIUM DIP"
    if a >= 5:      return "MINOR DIP"
    return "NEAR PEAK"


def _day_color(pct: float) -> tuple:
    if pct > 0: return C_GREEN
    if pct < 0: return C_RED
    return C_SUBTEXT


def build_group_image(group: dict, quotes: dict, date_str: str) -> bytes:
    """Build one PNG for a sector group (~900×900 px)."""
    sectors = [WISHLIST_SECTORS[i] for i in group["indices"]]

    img_h = H_HEADER + H_FOOTER
    for sec in sectors:
        img_h += H_SECTOR_BAR + H_COL_HEADER
        img_h += len(sec["stocks"]) * H_STOCK_ROW
        img_h += H_SECTOR_GAP

    img  = Image.new("RGB", (IMG_W, img_h), C_BG)
    draw = ImageDraw.Draw(img)

    f_title  = _find_font(20, bold=True)
    f_part   = _find_font(12, bold=True)
    f_sub    = _find_font(12, bold=False)
    f_sector = _find_font(14, bold=True)
    f_colhdr = _find_font(11, bold=True)
    f_sym    = _find_font(13, bold=True)
    f_name   = _find_font(11, bold=False)
    f_data   = _find_font(13, bold=False)
    f_datab  = _find_font(13, bold=True)
    f_flag   = _find_font(10, bold=True)
    f_note   = _find_font(10, bold=False)

    # Header
    draw.rectangle([(0, 0), (IMG_W, H_HEADER)], fill=C_CARD)
    draw.rectangle([(0, H_HEADER - 2), (IMG_W, H_HEADER)], fill=C_BORDER)
    _center(draw, 0, 10, IMG_W, "WISHLIST STOCK TRACKER", f_title, C_BLUE)
    _center(draw, 0, 38, IMG_W,
            f"Part {group['part']}  —  {group['label']}", f_part, C_GOLD)
    _center(draw, 0, 60, IMG_W, date_str, f_sub, C_SUBTEXT)

    y = H_HEADER

    for sec in sectors:
        sector_color = sec["color"]
        stocks       = sec["stocks"]

        # Sector bar
        r, g, b = sector_color
        draw.rectangle([(0, y), (IMG_W, y + H_SECTOR_BAR)],
                       fill=(max(0, r // 5), max(0, g // 5), max(0, b // 5)))
        draw.rectangle([(0, y), (5, y + H_SECTOR_BAR)], fill=sector_color)
        draw.text((14, y + (H_SECTOR_BAR - 14) // 2),
                  sec["sector"], font=f_sector, fill=sector_color)
        badge = f"{len(stocks)} stock{'s' if len(stocks) > 1 else ''}"
        draw.text((IMG_W - PAD - _tw(draw, badge, f_note),
                   y + (H_SECTOR_BAR - 10) // 2),
                  badge, font=f_note, fill=sector_color)
        y += H_SECTOR_BAR

        # Column header
        draw.rectangle([(0, y), (IMG_W, y + H_COL_HEADER)], fill=C_CARD2)
        draw.rectangle([(0, y + H_COL_HEADER - 1), (IMG_W, y + H_COL_HEADER)],
                       fill=C_BORDER)
        for ck, cl in COL_LABELS:
            _center(draw, COL_X[ck], y + 9, COL_W[ck], cl, f_colhdr, C_SUBTEXT)
        y += H_COL_HEADER

        # Stock rows
        for si, stk in enumerate(stocks):
            sym  = stk["symbol"]
            name = stk["name"]
            note = stk.get("note", "")
            q    = quotes.get(sym, {})

            row_bg = C_CARD if si % 2 == 0 else C_CARD2
            draw.rectangle([(0, y), (IMG_W, y + H_STOCK_ROW)], fill=row_bg)
            draw.rectangle([(PAD, y + H_STOCK_ROW - 1),
                             (IMG_W - PAD, y + H_STOCK_ROW)], fill=C_BORDER)

            ry1 = y + 7
            ry2 = y + 27

            if not validate_stock_data(q):
                # Show error / cache indicator
                src = q.get("source", "error")
                err_color = C_YELLOW if src == "cache" else C_RED
                draw.text((COL_X["stock"] + 4, ry1), sym,
                          font=f_sym, fill=err_color)
                label = "CACHED DATA" if src == "cache" else "DATA UNAVAILABLE"
                draw.text((COL_X["stock"] + 4, ry2), label,
                          font=f_name, fill=err_color)
                y += H_STOCK_ROW
                continue

            lp  = q["last_price"]
            h52 = q["high_52w"]
            l52 = q["low_52w"]
            pc  = q["p_change"]
            pfh = q["pct_from_high"]
            pfl = q["pct_from_low"]
            nwh = q["new_52w_high"]
            nwl = q["new_52w_low"]
            src = q.get("source", "")

            # Col 1 — Stock
            sym_col = C_RED if note == "EXITING" else C_TEXT
            draw.text((COL_X["stock"] + 4, ry1), sym,
                      font=f_sym, fill=sym_col)
            draw.text((COL_X["stock"] + 4, ry2), name,
                      font=f_name, fill=C_SUBTEXT)
            if note:
                nc = C_RED if note == "EXITING" else C_YELLOW
                draw.text((COL_X["stock"] + 4, ry2 + 12),
                          f"[{note}]", font=f_note, fill=nc)

            # Col 2 — Price  (dim if from cache)
            price_col = C_SUBTEXT if src == "cache" else C_TEXT
            _right(draw, COL_X["price"], ry1, COL_W["price"],
                   f"Rs.{lp:,.2f}", f_datab, price_col)
            if src == "cache":
                _right(draw, COL_X["price"], ry2, COL_W["price"],
                       "[cached]", f_note, C_YELLOW)

            # Col 3 — 52W High
            _right(draw, COL_X["high52w"], ry1, COL_W["high52w"],
                   f"Rs.{h52:,.2f}", f_data, C_SUBTEXT)

            # Col 4 — % from 52W High
            dc = _dip_color(pfh)
            _center(draw, COL_X["pct_high"], ry1, COL_W["pct_high"],
                    f"{pfh:+.2f}%", f_datab, dc)
            _center(draw, COL_X["pct_high"], ry2, COL_W["pct_high"],
                    _dip_label(pfh), f_note, dc)

            # Col 5 — 52W Low
            _right(draw, COL_X["low52w"], ry1, COL_W["low52w"],
                   f"Rs.{l52:,.2f}", f_data, C_SUBTEXT)
            _right(draw, COL_X["low52w"], ry2, COL_W["low52w"],
                   f"+{pfl:.1f}% from low", f_note, C_SUBTEXT)

            # Col 6 — Day Change %
            _center(draw, COL_X["day_chg"], ry1, COL_W["day_chg"],
                    f"{pc:+.2f}%", f_datab, _day_color(pc))
            dhl = f"H:{q['day_high']:,.0f}  L:{q['day_low']:,.0f}"
            _center(draw, COL_X["day_chg"], ry2, COL_W["day_chg"],
                    dhl, f_note, C_SUBTEXT)

            # Col 7 — 52W Flag
            fx = COL_X["flag"]
            fw = COL_W["flag"] - 4
            if nwh:
                draw.rectangle([(fx, y + 12), (fx + fw, y + 30)],
                               fill=(55, 45, 0))
                draw.rectangle([(fx, y + 12), (fx + fw, y + 30)],
                               outline=C_GOLD, width=1)
                _center(draw, fx, y + 15, fw, "NEW 52W HIGH", f_flag, C_GOLD)
            elif nwl:
                draw.rectangle([(fx, y + 12), (fx + fw, y + 30)],
                               fill=(55, 0, 0))
                draw.rectangle([(fx, y + 12), (fx + fw, y + 30)],
                               outline=C_RED, width=1)
                _center(draw, fx, y + 15, fw, "NEW 52W LOW", f_flag, C_RED)

            y += H_STOCK_ROW

        y += H_SECTOR_GAP

    # Footer
    draw.rectangle([(0, y), (IMG_W, y + H_FOOTER)], fill=C_CARD)
    draw.rectangle([(0, y), (IMG_W, y + 2)], fill=C_BORDER)
    guide = [
        ("<5% NEAR PEAK",    C_GREEN),
        ("5-9% MINOR DIP",   C_YELLOW),
        ("10-14% MED DIP",   C_ORANGE),
        ("15%+ DEEP DIP",    C_RED),
        ("20%+ CRASH ZONE",  C_RED),
    ]
    gx = PAD
    for gt, gc in guide:
        draw.text((gx, y + 10), gt, font=f_note, fill=gc)
        gx += _tw(draw, gt, f_note) + 20
    _center(draw, 0, y + 34, IMG_W,
            "Data via Yahoo Finance (NSE). Not financial advice. Educational only.",
            f_note, C_SUBTEXT)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()


def build_all_images(quotes: dict) -> list[tuple[bytes, str]]:
    """Returns [(image_bytes, caption), ...] for all 4 sector groups."""
    ist      = pytz.timezone("Asia/Kolkata")
    now      = datetime.now(ist)
    date_str = now.strftime("%d %b %Y  |  %I:%M %p IST")

    images = []
    for grp in SECTOR_GROUPS:
        print(f"  Building image Part {grp['part']}...")
        img_bytes = build_group_image(grp, quotes, date_str)
        caption = (
            f"<b>Wishlist Stock Tracker — Part {grp['part']}</b>\n"
            f"{grp['label']}\n"
            f"{date_str}"
        )
        images.append((img_bytes, caption))
        print(f"  Part {grp['part']}: {len(img_bytes):,} bytes")
    return images


def build_text_message(quotes: dict) -> str:
    """Plain-text fallback for when Pillow is unavailable."""
    ist      = pytz.timezone("Asia/Kolkata")
    now      = datetime.now(ist)
    date_str = now.strftime("%d %b %Y  |  %I:%M %p IST")

    lines = ["=" * 52,
             f"  WISHLIST STOCK TRACKER  —  {date_str}",
             "=" * 52]

    for sec in WISHLIST_SECTORS:
        lines.append(f"\n{sec['sector']}")
        lines.append("-" * 40)
        for stk in sec["stocks"]:
            sym  = stk["symbol"]
            note = stk.get("note", "")
            q    = quotes.get(sym, {})
            if not validate_stock_data(q):
                src = q.get("source", "error")
                lines.append(f"  {sym}: {'CACHED' if src == 'cache' else 'UNAVAILABLE'}")
                continue
            pfh  = q["pct_from_high"]
            flag = (" [NEW 52W HIGH!]" if q["new_52w_high"] else
                    " [NEW 52W LOW!]"  if q["new_52w_low"]  else "")
            ns   = f" [{note}]" if note else ""
            lines.append(
                f"  {sym}{ns}: Rs.{q['last_price']:,.2f} | "
                f"52wH Rs.{q['high_52w']:,.2f} ({pfh:+.2f}% {_dip_label(pfh)}) | "
                f"52wL Rs.{q['low_52w']:,.2f} | Day {q['p_change']:+.2f}%{flag}"
            )

    lines += ["\n" + "=" * 52,
              "Data via Yahoo Finance (NSE). Not financial advice.",
              "=" * 52]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 7 — TELEGRAM DELIVERY
# ═══════════════════════════════════════════════════════════════════════════════

def _send_photo(bot_token: str, chat_id: str,
                image_bytes: bytes, caption: str) -> bool:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("wishlist.png", image_bytes, "image/png")},
            timeout=60,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        print(f"  [Telegram] sendPhoto to {chat_id} failed: {exc}")
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
               images: list, text_msg: str) -> None:
    chat_ids = [c.strip() for c in chat_ids_str.split(",") if c.strip()]
    for chat_id in chat_ids:
        print(f"  Sending to {chat_id}...")
        if images and PIL_AVAILABLE:
            for img_bytes, caption in images:
                ok = _send_photo(bot_token, chat_id, img_bytes, caption)
                if not ok:
                    _send_message(bot_token, chat_id, text_msg)
                    break
                time.sleep(1.5)
        else:
            _send_message(bot_token, chat_id, text_msg)
        time.sleep(2)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def get_unique_symbols() -> list[str]:
    """Return deduplicated list of all NSE symbols across all sectors."""
    seen: dict[str, bool] = {}
    for sec in WISHLIST_SECTORS:
        for stk in sec["stocks"]:
            seen[stk["symbol"]] = True
    return list(seen.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    print(f"\n{'='*60}")
    print(f"  WISHLIST STOCK TRACKER  —  {now.strftime('%d %b %Y  %I:%M %p IST')}")
    print(f"{'='*60}\n")

    # ── Credentials ───────────────────────────────────────────────────────────
    bot_token    = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids_str = os.environ.get("WISHLIST_TELEGRAM_CHAT_IDS", "").strip()

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
    cached_count = len(cache.get("stocks", {}))
    print(f"  Cache loaded: {cached_count} entries "
          f"(last updated: {cache.get('last_updated', 'never')})\n")

    # ── Step 2: Fetch live data ───────────────────────────────────────────────
    print("Step 2: Fetching live data via Yahoo Finance...")
    provider  = YahooFinanceProvider()
    live_data = provider.get_all_stocks(symbols)
    live_ok   = sum(1 for d in live_data.values() if validate_stock_data(d))
    print(f"  Live fetch: {live_ok}/{len(symbols)} symbols OK\n")

    # ── Step 3: Validate + cache fallback + score ─────────────────────────────
    print("Step 3: Validating, resolving cache fallbacks, scoring...")
    quotes: dict[str, dict] = {}
    for sym in symbols:
        resolved      = resolve_with_cache(sym, live_data[sym], cache)
        quotes[sym]   = score_opportunity(resolved)
        src           = quotes[sym].get("source", "error")
        valid         = validate_stock_data(quotes[sym])
        status        = f"OK ({src})" if valid else f"FAIL ({quotes[sym].get('error', '?')})"
        print(f"  {sym:<14} {status}")

    # ── Step 4: Update and save cache ─────────────────────────────────────────
    print("\nStep 4: Updating cache...")
    cache = update_cache(cache, quotes)
    save_cache(cache)

    # ── Step 5: Build images ──────────────────────────────────────────────────
    images: list = []
    if PIL_AVAILABLE:
        print("\nStep 5: Building 4 sector-group images...")
        try:
            images = build_all_images(quotes)
            print(f"  {len(images)} images built.\n")
        except Exception as exc:
            print(f"  WARNING: Image build failed: {exc}\n")

    # ── Step 6: Build text fallback ───────────────────────────────────────────
    text_msg = build_text_message(quotes)

    # ── Step 7: Send to Telegram ──────────────────────────────────────────────
    print("Step 6: Sending to Telegram...")
    notify_all(bot_token, chat_ids_str, images, text_msg)
    print("\nDone!")


if __name__ == "__main__":
    main()
