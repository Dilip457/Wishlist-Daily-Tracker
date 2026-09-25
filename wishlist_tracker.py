"""
Wishlist Stock Daily Tracker
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Data   : NSE India official API  —  equity-stockIndices endpoint
         (same type as allIndices used in the main market alert — works from
          GitHub Actions without 403 errors)
         Fetches NIFTY 500 + NIFTY MICROCAP 250 to cover all wishlist stocks.
         Returns yearHigh / yearLow / lastPrice / pChange / dayHigh / dayLow.
Notify : Telegram group / channel  (WISHLIST_TELEGRAM_CHAT_IDS secret)
Output : 4 sector-group PNG images (~900×900 px each) sent via Telegram.
         Falls back to plain-text sendMessage if Pillow is not installed.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import io
import time
import requests
import pytz
from datetime import datetime
from urllib.parse import quote as url_quote

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("WARNING: Pillow not installed — falling back to text messages.")

# ── Sector-wise Wishlist Configuration ───────────────────────────────────────
# symbol : Exact NSE equity symbol
# name   : Human-readable display name
# note   : Optional tag  ("EXITING", "highly valued", etc.)
WISHLIST_SECTORS = [
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

# ── Sector groups for 4 separate images (5 sectors each) ─────────────────────
# Each image is ~900×900 px — compact and readable on mobile
SECTOR_GROUPS = [
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

# ── NSE indices to fetch (covers all wishlist stocks) ─────────────────────────
NSE_EQUITY_INDICES = [
    "NIFTY 500",          # covers ~500 large/mid/small cap stocks
    "NIFTY MICROCAP 250", # covers micro-cap stocks (MOSCHIP, NETWEB, etc.)
]

# ── NSE Request Headers ───────────────────────────────────────────────────────
# Keep identical to the working market_alert.py — do NOT add Sec-Fetch-* or
# X-Requested-With here; those are browser-internal headers that NSE uses to
# distinguish page loads from XHR calls. Setting them on page visits causes
# NSE to return an empty body, breaking cookie setup.
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.nseindia.com/",
}

MAX_RETRIES  = 3
TIMEOUT_HOME = 30
TIMEOUT_API  = 30

# ── Image Palette ─────────────────────────────────────────────────────────────
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

IMG_W = 900
PAD   = 20

# Column x-positions and widths (usable = 860 px)
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


# ── Font Loader ───────────────────────────────────────────────────────────────
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


def _tw(draw, text, font):
    try:
        b = draw.textbbox((0, 0), text, font=font)
        return b[2] - b[0]
    except Exception:
        return len(text) * 8


def _center(draw, x, y, w, text, font, color):
    tw = _tw(draw, text, font)
    draw.text((x + (w - tw) // 2, y), text, font=font, fill=color)


def _right(draw, x, y, w, text, font, color):
    tw = _tw(draw, text, font)
    draw.text((x + w - tw - 4, y), text, font=font, fill=color)


# ── Signal Helpers ────────────────────────────────────────────────────────────
def _dip_color(pct):
    a = abs(pct)
    if a >= 15: return C_RED
    if a >= 10: return C_ORANGE
    if a >= 5:  return C_YELLOW
    return C_GREEN


def _dip_label(pct):
    if pct >= 0:    return "AT/NEAR PEAK"
    a = abs(pct)
    if a >= 20:     return "CRASH ZONE"
    if a >= 15:     return "DEEP DIP"
    if a >= 10:     return "MEDIUM DIP"
    if a >= 5:      return "MINOR DIP"
    return "NEAR PEAK"


def _day_color(pct):
    if pct > 0: return C_GREEN
    if pct < 0: return C_RED
    return C_SUBTEXT


# ── NSE Session ───────────────────────────────────────────────────────────────
def build_nse_session() -> requests.Session:
    """
    Identical session-building strategy to the working market_alert.py:
      1. Visit homepage  (sets initial cookies)
      2. Visit equity market page  (sets cookies for equity-stockIndices)
    No warm-up API call — that caused empty-body failures.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            session = requests.Session()
            session.headers.update(NSE_HEADERS)

            print(f"  [Attempt {attempt}] Visiting NSE homepage for cookies...")
            session.get("https://www.nseindia.com", timeout=TIMEOUT_HOME)
            time.sleep(3)

            print(f"  [Attempt {attempt}] Visiting equity market page...")
            session.headers.update(
                {"Referer": "https://www.nseindia.com/"}
            )
            session.get(
                "https://www.nseindia.com/market-data/live-equity-market",
                timeout=TIMEOUT_HOME,
            )
            time.sleep(2)

            return session
        except Exception as e:
            print(f"  WARNING: Session attempt {attempt} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(attempt * 10)
            else:
                raise RuntimeError(f"NSE session failed: {e}") from e


# ── Fetch equity-stockIndices (same endpoint type as allIndices) ──────────────
def fetch_equity_index(session: requests.Session, index_name: str) -> list:
    """
    Fetch all stocks in an NSE equity index.
    Strategy:
      1. Visit the specific index page (sets cookies + correct Referer)
      2. Call equity-stockIndices API with that Referer
    Same pattern as allIndices — works from GitHub Actions.
    """
    encoded  = url_quote(index_name)
    page_url = (f"https://www.nseindia.com/market-data/live-equity-market"
                f"?index={encoded}")
    api_url  = f"https://www.nseindia.com/api/equity-stockIndices?index={encoded}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Step A: visit the specific index page — this sets the cookies
            # and Referer that NSE requires for equity-stockIndices.
            print(f"    [Attempt {attempt}] Visiting index page: {index_name}...")
            session.headers.update(
                {"Referer": "https://www.nseindia.com/market-data/live-equity-market"}
            )
            session.get(page_url, timeout=TIMEOUT_HOME)
            time.sleep(2)

            # Step B: call the API — Referer must be the index page URL
            print(f"    [Attempt {attempt}] Calling equity-stockIndices: {index_name}...")
            session.headers.update({"Referer": page_url})
            resp = session.get(api_url, timeout=TIMEOUT_API)

            # Log status for debugging
            print(f"    HTTP {resp.status_code}  body_len={len(resp.content)} bytes")
            resp.raise_for_status()

            if not resp.content:
                raise ValueError(f"Empty response body for {index_name}")

            data = resp.json().get("data", [])
            # First row is the index summary row — skip it
            stocks = [
                d for d in data
                if d.get("symbol") and d.get("symbol") not in (index_name, "")
            ]
            print(f"    OK: {len(stocks)} stocks in {index_name}")
            return stocks
        except Exception as e:
            print(f"    WARNING: {index_name} attempt {attempt} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(attempt * 10)
            else:
                print(f"    ERROR: Could not fetch {index_name} after {MAX_RETRIES} attempts")
                return []


# ── Build stock lookup from all fetched indices ───────────────────────────────
def fetch_all_wishlist_data(session: requests.Session) -> dict:
    """
    Fetch quotes for all wishlist stocks.
    Strategy: fetch NIFTY 500 + NIFTY MICROCAP 250 → build lookup dict.
    Returns {symbol: quote_dict}
    """
    # ── Step 1: Build master lookup from NSE indices ──────────────────────────
    master_lookup = {}
    for idx_name in NSE_EQUITY_INDICES:
        print(f"  Fetching index data: {idx_name}...")
        stocks = fetch_equity_index(session, idx_name)
        for item in stocks:
            sym = item.get("symbol", "").strip()
            if sym and sym not in master_lookup:
                master_lookup[sym] = item
        time.sleep(2)

    print(f"  Master lookup built: {len(master_lookup)} unique stocks\n")

    # ── Step 2: Map wishlist symbols to their data ────────────────────────────
    unique_symbols = {}
    for sec in WISHLIST_SECTORS:
        for stk in sec["stocks"]:
            unique_symbols[stk["symbol"]] = True

    def _f(val):
        try:
            return float(val or 0)
        except (TypeError, ValueError):
            return 0.0

    quotes = {}
    for sym in unique_symbols:
        item = master_lookup.get(sym)
        if item:
            last_price  = _f(item.get("lastPrice"))
            high_52w    = _f(item.get("yearHigh"))
            low_52w     = _f(item.get("yearLow"))
            day_high    = _f(item.get("dayHigh"))
            day_low     = _f(item.get("dayLow"))
            p_change    = _f(item.get("pChange"))
            prev_close  = _f(item.get("previousClose"))

            pct_from_high = (
                round((last_price - high_52w) / high_52w * 100, 2)
                if high_52w else 0.0
            )
            pct_from_low = (
                round((last_price - low_52w) / low_52w * 100, 2)
                if low_52w else 0.0
            )
            new_52w_high = high_52w > 0 and last_price >= high_52w * 0.9995
            new_52w_low  = low_52w  > 0 and last_price <= low_52w  * 1.0005

            print(f"  OK {sym}: Rs.{last_price:,.2f}  "
                  f"52wH={high_52w:,.2f}  52wL={low_52w:,.2f}  "
                  f"day={p_change:+.2f}%")

            quotes[sym] = {
                "symbol":        sym,
                "last_price":    last_price,
                "high_52w":      high_52w,
                "low_52w":       low_52w,
                "day_high":      day_high,
                "day_low":       day_low,
                "p_change":      p_change,
                "prev_close":    prev_close,
                "pct_from_high": pct_from_high,
                "pct_from_low":  pct_from_low,
                "new_52w_high":  new_52w_high,
                "new_52w_low":   new_52w_low,
                "error":         None,
            }
        else:
            print(f"  WARNING: {sym} not found in fetched indices")
            quotes[sym] = {
                "symbol":        sym,
                "last_price":    0.0, "high_52w":    0.0, "low_52w":     0.0,
                "day_high":      0.0, "day_low":     0.0, "p_change":    0.0,
                "prev_close":    0.0, "pct_from_high": 0.0, "pct_from_low": 0.0,
                "new_52w_high":  False, "new_52w_low": False,
                "error":         "Not found in NIFTY 500 / NIFTY MICROCAP 250",
            }

    return quotes


# ── Build one sector-group image ──────────────────────────────────────────────
def build_group_image(group: dict, quotes: dict, date_str: str) -> bytes:
    """
    Build a PNG for one sector group (5 sectors, ~900×900 px).
    """
    sectors = [WISHLIST_SECTORS[i] for i in group["indices"]]

    # Calculate height
    img_h = H_HEADER + H_FOOTER
    for sec in sectors:
        img_h += H_SECTOR_BAR + H_COL_HEADER
        img_h += len(sec["stocks"]) * H_STOCK_ROW
        img_h += H_SECTOR_GAP

    img  = Image.new("RGB", (IMG_W, img_h), C_BG)
    draw = ImageDraw.Draw(img)

    # Fonts
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

    # ── Header ────────────────────────────────────────────────────────────────
    draw.rectangle([(0, 0), (IMG_W, H_HEADER)], fill=C_CARD)
    draw.rectangle([(0, H_HEADER - 2), (IMG_W, H_HEADER)], fill=C_BORDER)

    title = "WISHLIST STOCK TRACKER"
    _center(draw, 0, 10, IMG_W, title, f_title, C_BLUE)

    part_str = f"Part {group['part']}  —  {group['label']}"
    _center(draw, 0, 38, IMG_W, part_str, f_part, C_GOLD)

    _center(draw, 0, 60, IMG_W, date_str, f_sub, C_SUBTEXT)

    # ── Sector sections ───────────────────────────────────────────────────────
    y = H_HEADER

    for sec in sectors:
        sector_name  = sec["sector"]
        sector_color = sec["color"]
        stocks       = sec["stocks"]

        # Sector header bar
        r, g, b = sector_color
        bg = (max(0, r // 5), max(0, g // 5), max(0, b // 5))
        draw.rectangle([(0, y), (IMG_W, y + H_SECTOR_BAR)], fill=bg)
        draw.rectangle([(0, y), (5, y + H_SECTOR_BAR)], fill=sector_color)
        draw.text((14, y + (H_SECTOR_BAR - 14) // 2),
                  sector_name, font=f_sector, fill=sector_color)
        badge = f"{len(stocks)} stock{'s' if len(stocks) > 1 else ''}"
        bw = _tw(draw, badge, f_note)
        draw.text((IMG_W - PAD - bw, y + (H_SECTOR_BAR - 10) // 2),
                  badge, font=f_note, fill=sector_color)
        y += H_SECTOR_BAR

        # Column header row
        draw.rectangle([(0, y), (IMG_W, y + H_COL_HEADER)], fill=C_CARD2)
        draw.rectangle([(0, y + H_COL_HEADER - 1), (IMG_W, y + H_COL_HEADER)],
                       fill=C_BORDER)
        for col_key, col_label in COL_LABELS:
            _center(draw, COL_X[col_key], y + 9, COL_W[col_key],
                    col_label, f_colhdr, C_SUBTEXT)
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

            ry1 = y + 7    # symbol line
            ry2 = y + 27   # name / sub-data line

            if q.get("error"):
                draw.text((COL_X["stock"] + 4, ry1), sym,
                          font=f_sym, fill=C_RED)
                draw.text((COL_X["stock"] + 4, ry2), "DATA UNAVAILABLE",
                          font=f_name, fill=C_RED)
                y += H_STOCK_ROW
                continue

            lp   = q["last_price"]
            h52  = q["high_52w"]
            l52  = q["low_52w"]
            pc   = q["p_change"]
            pfh  = q["pct_from_high"]
            pfl  = q["pct_from_low"]
            nwh  = q["new_52w_high"]
            nwl  = q["new_52w_low"]

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

            # Col 2 — Price
            _right(draw, COL_X["price"], ry1, COL_W["price"],
                   f"Rs.{lp:,.2f}", f_datab, C_TEXT)

            # Col 3 — 52W High
            _right(draw, COL_X["high52w"], ry1, COL_W["high52w"],
                   f"Rs.{h52:,.2f}", f_data, C_SUBTEXT)

            # Col 4 — % from 52W High  (color-coded)
            dc = _dip_color(pfh)
            dl = _dip_label(pfh)
            _center(draw, COL_X["pct_high"], ry1, COL_W["pct_high"],
                    f"{pfh:+.2f}%", f_datab, dc)
            _center(draw, COL_X["pct_high"], ry2, COL_W["pct_high"],
                    dl, f_note, dc)

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

    # ── Footer ────────────────────────────────────────────────────────────────
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

    disc = "Data via NSE India (official). Not financial advice. Educational purpose only."
    _center(draw, 0, y + 34, IMG_W, disc, f_note, C_SUBTEXT)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()


# ── Build all 4 group images ──────────────────────────────────────────────────
def build_all_images(quotes: dict) -> list:
    """Returns list of (image_bytes, caption) for each sector group."""
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


# ── Plain-text fallback ───────────────────────────────────────────────────────
def build_text_message(quotes: dict) -> str:
    ist      = pytz.timezone("Asia/Kolkata")
    now      = datetime.now(ist)
    date_str = now.strftime("%d %b %Y  |  %I:%M %p IST")

    lines = ["=" * 52, f"  WISHLIST STOCK TRACKER  —  {date_str}", "=" * 52]

    for sec in WISHLIST_SECTORS:
        lines.append(f"\n{sec['sector']}")
        lines.append("-" * 40)
        for stk in sec["stocks"]:
            sym  = stk["symbol"]
            note = stk.get("note", "")
            q    = quotes.get(sym, {})
            if q.get("error"):
                lines.append(f"  {sym}: DATA UNAVAILABLE")
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
              "Data via NSE India. Not financial advice.", "=" * 52]
    return "\n".join(lines)


# ── Telegram ──────────────────────────────────────────────────────────────────
def send_photo(bot_token: str, chat_id: str,
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
    except Exception as e:
        print(f"  WARNING: sendPhoto to {chat_id} failed: {e}")
        return False


def send_message(bot_token: str, chat_id: str, text: str) -> bool:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=30,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"  WARNING: sendMessage to {chat_id} failed: {e}")
        return False


def notify_all(bot_token: str, chat_ids_str: str,
               images: list, text_msg: str) -> None:
    chat_ids = [c.strip() for c in chat_ids_str.split(",") if c.strip()]
    for chat_id in chat_ids:
        print(f"  Sending to {chat_id}...")
        if images and PIL_AVAILABLE:
            for img_bytes, caption in images:
                ok = send_photo(bot_token, chat_id, img_bytes, caption)
                if not ok:
                    send_message(bot_token, chat_id, text_msg)
                    break
                time.sleep(1.5)
        else:
            send_message(bot_token, chat_id, text_msg)
        time.sleep(2)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    print(f"\n{'='*60}")
    print(f"  WISHLIST STOCK TRACKER  —  {now.strftime('%d %b %Y  %I:%M %p IST')}")
    print(f"{'='*60}\n")

    bot_token    = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids_str = os.environ.get("WISHLIST_TELEGRAM_CHAT_IDS", "").strip()

    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable not set.")
    if not chat_ids_str:
        raise RuntimeError(
            "WISHLIST_TELEGRAM_CHAT_IDS not set.\n"
            "Add it in GitHub → Settings → Secrets and variables → Actions."
        )

    # Step 1 — NSE session
    print("Step 1: Building NSE session...")
    session = build_nse_session()
    print("  NSE session ready.\n")

    # Step 2 — Fetch stock data via equity-stockIndices
    print("Step 2: Fetching stock data from NSE equity indices...")
    quotes = fetch_all_wishlist_data(session)
    found  = sum(1 for q in quotes.values() if not q.get("error"))
    print(f"\n  {found}/{len(quotes)} symbols fetched successfully.\n")

    # Step 3 — Build 4 sector-group images
    images = []
    if PIL_AVAILABLE:
        print("Step 3: Building 4 sector-group images...")
        try:
            images = build_all_images(quotes)
            print(f"  {len(images)} images built.\n")
        except Exception as e:
            print(f"  WARNING: Image build failed: {e}\n")

    # Step 4 — Build text fallback
    text_msg = build_text_message(quotes)

    # Step 5 — Send to Telegram
    print("Step 4: Sending to Telegram...")
    notify_all(bot_token, chat_ids_str, images, text_msg)
    print("\nDone!")


if __name__ == "__main__":
    main()
