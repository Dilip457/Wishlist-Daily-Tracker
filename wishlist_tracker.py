"""
Wishlist Stock Daily Tracker
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Data   : NSE India official API (quote-equity endpoint)
         Returns lastPrice, weekHighLow (52W high/low), intraDayHighLow,
         pChange (day % change) — same data as nseindia.com
Notify : Telegram group / channel (WISHLIST_TELEGRAM_CHAT_IDS secret)
Output : Sector-wise infographic PNG sent via Telegram sendPhoto
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
# symbol  : Exact NSE equity symbol (case-sensitive)
# name    : Human-readable display name
# note    : Optional tag shown in the image (e.g. "EXITING", "highly valued")
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

# ── NSE Request Headers ───────────────────────────────────────────────────────
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

# ── Image Palette (GitHub-dark inspired) ─────────────────────────────────────
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
C_WHITE   = (255, 255, 255)

IMG_W = 900
PAD   = 20

# Column x-positions and widths (total usable = 860px)
COL_X = {
    "stock":    PAD,           # Stock symbol + name
    "price":    PAD + 175,     # Current price
    "high52w":  PAD + 295,     # 52W High
    "pct_high": PAD + 415,     # % from 52W High
    "low52w":   PAD + 540,     # 52W Low
    "day_chg":  PAD + 660,     # Day Change %
    "flag":     PAD + 770,     # NEW 52W HIGH/LOW flag
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

# Row heights
H_HEADER      = 90   # Top header
H_COL_HEADER  = 30   # Column label row
H_SECTOR_BAR  = 42   # Sector name bar
H_STOCK_ROW   = 48   # Each stock data row
H_SECTOR_GAP  = 8    # Gap between sectors
H_FOOTER      = 58   # Bottom footer


# ── Font Loader ───────────────────────────────────────────────────────────────
def _find_font(size: int, bold: bool = False):
    if not PIL_AVAILABLE:
        return None
    candidates_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
    ]
    candidates_reg = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]
    candidates = candidates_bold if bold else candidates_reg
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _text_w(draw, text: str, font) -> int:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    except Exception:
        return len(text) * 8


def _draw_text_centered(draw, x, y, w, text, font, color):
    """Draw text centered within a box of width w starting at x."""
    tw = _text_w(draw, text, font)
    tx = x + (w - tw) // 2
    draw.text((tx, y), text, font=font, fill=color)


def _draw_text_right(draw, x, y, w, text, font, color):
    """Draw text right-aligned within a box of width w starting at x."""
    tw = _text_w(draw, text, font)
    tx = x + w - tw - 4
    draw.text((tx, y), text, font=font, fill=color)


# ── Signal Helpers ────────────────────────────────────────────────────────────
def _dip_color(pct_from_high: float) -> tuple:
    """Color based on % below 52W high (pct_from_high is negative when below)."""
    a = abs(pct_from_high)
    if a >= 20: return C_RED
    if a >= 15: return C_RED
    if a >= 10: return C_ORANGE
    if a >= 5:  return C_YELLOW
    return C_GREEN


def _dip_label(pct_from_high: float) -> str:
    a = abs(pct_from_high)
    if pct_from_high >= 0:  return "AT/NEAR PEAK"
    if a >= 20: return "CRASH ZONE"
    if a >= 15: return "DEEP DIP"
    if a >= 10: return "MEDIUM DIP"
    if a >= 5:  return "MINOR DIP"
    return "NEAR PEAK"


def _day_chg_color(pct: float) -> tuple:
    if pct > 0:  return C_GREEN
    if pct < 0:  return C_RED
    return C_SUBTEXT


# ── NSE Session Builder ───────────────────────────────────────────────────────
def build_nse_session() -> requests.Session:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            session = requests.Session()
            session.headers.update(NSE_HEADERS)
            print(f"  [Attempt {attempt}] Visiting NSE homepage for cookies...")
            session.get("https://www.nseindia.com", timeout=TIMEOUT_HOME)
            time.sleep(3)
            print(f"  [Attempt {attempt}] Visiting equity market page...")
            session.get(
                "https://www.nseindia.com/market-data/live-equity-market",
                timeout=TIMEOUT_HOME,
            )
            time.sleep(2)
            return session
        except Exception as e:
            print(f"  WARNING: Session attempt {attempt} failed: {e}")
            if attempt < MAX_RETRIES:
                wait = attempt * 10
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"NSE session failed after {MAX_RETRIES} attempts: {e}"
                ) from e


# ── Fetch Individual Stock Quote ──────────────────────────────────────────────
def fetch_stock_quote(session: requests.Session, symbol: str) -> dict:
    """
    Fetch live quote for a single NSE equity symbol.
    Returns a dict with price, 52W high/low, day change, etc.
    On error, returns a dict with error key set.
    """
    encoded = url_quote(symbol)
    url = f"https://www.nseindia.com/api/quote-equity?symbol={encoded}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"    Fetching {symbol} (attempt {attempt})...")
            resp = session.get(url, timeout=TIMEOUT_API)
            resp.raise_for_status()
            data = resp.json()

            pi   = data.get("priceInfo", {})
            whl  = pi.get("weekHighLow", {})
            idhl = pi.get("intraDayHighLow", {})

            def _f(val):
                try:
                    return float(val or 0)
                except (TypeError, ValueError):
                    return 0.0

            last_price  = _f(pi.get("lastPrice"))
            high_52w    = _f(whl.get("max"))
            low_52w     = _f(whl.get("min"))
            day_high    = _f(idhl.get("max"))
            day_low     = _f(idhl.get("min"))
            p_change    = _f(pi.get("pChange"))
            prev_close  = _f(pi.get("previousClose"))

            # % from 52W high (negative = below high)
            pct_from_high = (
                round((last_price - high_52w) / high_52w * 100, 2)
                if high_52w else 0.0
            )
            # % above 52W low (positive = above low)
            pct_from_low = (
                round((last_price - low_52w) / low_52w * 100, 2)
                if low_52w else 0.0
            )

            # Detect if today's price is at/above 52W high or at/below 52W low
            # (NSE already updates 52W values intraday, so equality means new record)
            new_52w_high = high_52w > 0 and last_price >= high_52w * 0.9995
            new_52w_low  = low_52w  > 0 and last_price <= low_52w  * 1.0005

            print(f"    OK {symbol}: price={last_price}, 52wH={high_52w}, "
                  f"52wL={low_52w}, day%={p_change:+.2f}%")

            return {
                "symbol":        symbol,
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

        except Exception as e:
            print(f"    WARNING: {symbol} attempt {attempt} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(attempt * 5)
            else:
                return {
                    "symbol":        symbol,
                    "last_price":    0.0,
                    "high_52w":      0.0,
                    "low_52w":       0.0,
                    "day_high":      0.0,
                    "day_low":       0.0,
                    "p_change":      0.0,
                    "prev_close":    0.0,
                    "pct_from_high": 0.0,
                    "pct_from_low":  0.0,
                    "new_52w_high":  False,
                    "new_52w_low":   False,
                    "error":         str(e),
                }


# ── Fetch All Wishlist Stocks ─────────────────────────────────────────────────
def fetch_all_wishlist_data(session: requests.Session) -> dict:
    """
    Fetch quotes for all unique symbols across all sectors.
    Returns {symbol: quote_dict}
    """
    # Collect unique symbols
    unique_symbols = {}
    for sec in WISHLIST_SECTORS:
        for stk in sec["stocks"]:
            sym = stk["symbol"]
            if sym not in unique_symbols:
                unique_symbols[sym] = True

    quotes = {}
    total = len(unique_symbols)
    for i, sym in enumerate(unique_symbols, 1):
        print(f"  [{i}/{total}] Fetching {sym}...")
        quotes[sym] = fetch_stock_quote(session, sym)
        time.sleep(0.8)  # polite delay between requests

    return quotes


# ── Calculate Image Height ────────────────────────────────────────────────────
def _calc_image_height() -> int:
    h = H_HEADER + H_FOOTER
    for sec in WISHLIST_SECTORS:
        h += H_SECTOR_BAR + H_COL_HEADER
        h += len(sec["stocks"]) * H_STOCK_ROW
        h += H_SECTOR_GAP
    return h


# ── Build Infographic Image ───────────────────────────────────────────────────
def build_wishlist_image(quotes: dict) -> bytes:
    """
    Build a sector-wise infographic PNG.
    Returns PNG bytes.
    """
    ist  = pytz.timezone("Asia/Kolkata")
    now  = datetime.now(ist)
    date_str = now.strftime("%d %b %Y  |  %I:%M %p IST")

    img_h = _calc_image_height()
    img   = Image.new("RGB", (IMG_W, img_h), C_BG)
    draw  = ImageDraw.Draw(img)

    # ── Fonts ─────────────────────────────────────────────────────────────────
    f_title   = _find_font(22, bold=True)
    f_sub     = _find_font(13, bold=False)
    f_sector  = _find_font(15, bold=True)
    f_col_hdr = _find_font(11, bold=True)
    f_sym     = _find_font(13, bold=True)
    f_name    = _find_font(11, bold=False)
    f_data    = _find_font(13, bold=False)
    f_data_b  = _find_font(13, bold=True)
    f_flag    = _find_font(10, bold=True)
    f_note    = _find_font(10, bold=False)

    # ── Header ────────────────────────────────────────────────────────────────
    # Gradient-like header background
    draw.rectangle([(0, 0), (IMG_W, H_HEADER)], fill=C_CARD)
    draw.rectangle([(0, H_HEADER - 2), (IMG_W, H_HEADER)], fill=C_BORDER)

    # Title
    title = "WISHLIST STOCK TRACKER"
    tw = _text_w(draw, title, f_title)
    draw.text(((IMG_W - tw) // 2, 14), title, font=f_title, fill=C_BLUE)

    # Subtitle
    sub1 = "Sector-wise  |  52W High / Low Analysis  |  Daily Dip Monitor"
    sw = _text_w(draw, sub1, f_sub)
    draw.text(((IMG_W - sw) // 2, 44), sub1, font=f_sub, fill=C_SUBTEXT)

    # Date
    dw = _text_w(draw, date_str, f_sub)
    draw.text(((IMG_W - dw) // 2, 64), date_str, font=f_sub, fill=C_TEXT)

    # ── Column header labels (reference row) ─────────────────────────────────
    COL_LABELS = [
        ("stock",    "STOCK"),
        ("price",    "PRICE"),
        ("high52w",  "52W HIGH"),
        ("pct_high", "% FROM HIGH"),
        ("low52w",   "52W LOW"),
        ("day_chg",  "DAY CHG%"),
        ("flag",     "52W FLAG"),
    ]

    # ── Sector Sections ───────────────────────────────────────────────────────
    y = H_HEADER

    for sec_idx, sec in enumerate(WISHLIST_SECTORS):
        sector_name  = sec["sector"]
        sector_color = sec["color"]
        stocks       = sec["stocks"]

        # ── Sector header bar ─────────────────────────────────────────────────
        # Darker tinted background
        r, g, b = sector_color
        bg_color = (max(0, r // 5), max(0, g // 5), max(0, b // 5))
        draw.rectangle([(0, y), (IMG_W, y + H_SECTOR_BAR)], fill=bg_color)

        # Left accent stripe
        draw.rectangle([(0, y), (5, y + H_SECTOR_BAR)], fill=sector_color)

        # Sector name
        sec_text = f"  {sector_name}"
        draw.text((12, y + (H_SECTOR_BAR - 15) // 2), sec_text,
                  font=f_sector, fill=sector_color)

        # Stock count badge
        badge = f"{len(stocks)} stock{'s' if len(stocks) > 1 else ''}"
        bw = _text_w(draw, badge, f_note)
        draw.text((IMG_W - PAD - bw, y + (H_SECTOR_BAR - 10) // 2),
                  badge, font=f_note, fill=sector_color)

        y += H_SECTOR_BAR

        # ── Column header row ─────────────────────────────────────────────────
        draw.rectangle([(0, y), (IMG_W, y + H_COL_HEADER)], fill=C_CARD2)
        draw.rectangle([(0, y + H_COL_HEADER - 1), (IMG_W, y + H_COL_HEADER)],
                       fill=C_BORDER)

        for col_key, col_label in COL_LABELS:
            cx = COL_X[col_key]
            cw = COL_W[col_key]
            _draw_text_centered(draw, cx, y + 9, cw, col_label, f_col_hdr, C_SUBTEXT)

        y += H_COL_HEADER

        # ── Stock rows ────────────────────────────────────────────────────────
        for stk_idx, stk in enumerate(stocks):
            sym   = stk["symbol"]
            name  = stk["name"]
            note  = stk.get("note", "")
            q     = quotes.get(sym, {})

            # Alternating row background
            row_bg = C_CARD if stk_idx % 2 == 0 else C_CARD2
            draw.rectangle([(0, y), (IMG_W, y + H_STOCK_ROW)], fill=row_bg)

            # Bottom border
            draw.rectangle([(PAD, y + H_STOCK_ROW - 1),
                             (IMG_W - PAD, y + H_STOCK_ROW)], fill=C_BORDER)

            row_y_sym  = y + 6
            row_y_name = y + 26

            if q.get("error"):
                # Error state
                draw.text((COL_X["stock"], row_y_sym), sym,
                          font=f_sym, fill=C_RED)
                draw.text((COL_X["stock"], row_y_name), "DATA UNAVAILABLE",
                          font=f_name, fill=C_RED)
                y += H_STOCK_ROW
                continue

            last_price    = q["last_price"]
            high_52w      = q["high_52w"]
            low_52w       = q["low_52w"]
            p_change      = q["p_change"]
            pct_from_high = q["pct_from_high"]
            pct_from_low  = q["pct_from_low"]
            new_52w_high  = q["new_52w_high"]
            new_52w_low   = q["new_52w_low"]

            # ── Col 1: Stock symbol + name ────────────────────────────────────
            sym_color = C_RED if note == "EXITING" else C_TEXT
            draw.text((COL_X["stock"] + 4, row_y_sym), sym,
                      font=f_sym, fill=sym_color)
            draw.text((COL_X["stock"] + 4, row_y_name), name,
                      font=f_name, fill=C_SUBTEXT)
            if note:
                note_color = C_RED if note == "EXITING" else C_YELLOW
                draw.text((COL_X["stock"] + 4, row_y_name + 12), f"[{note}]",
                          font=f_note, fill=note_color)

            # ── Col 2: Current Price ──────────────────────────────────────────
            price_str = f"Rs.{last_price:,.2f}"
            _draw_text_right(draw, COL_X["price"], row_y_sym,
                             COL_W["price"], price_str, f_data_b, C_TEXT)

            # ── Col 3: 52W High ───────────────────────────────────────────────
            high_str = f"Rs.{high_52w:,.2f}"
            _draw_text_right(draw, COL_X["high52w"], row_y_sym,
                             COL_W["high52w"], high_str, f_data, C_SUBTEXT)

            # ── Col 4: % from 52W High ────────────────────────────────────────
            dip_col   = _dip_color(pct_from_high)
            dip_lbl   = _dip_label(pct_from_high)
            pct_str   = f"{pct_from_high:+.2f}%"
            _draw_text_centered(draw, COL_X["pct_high"], row_y_sym,
                                COL_W["pct_high"], pct_str, f_data_b, dip_col)
            _draw_text_centered(draw, COL_X["pct_high"], row_y_name,
                                COL_W["pct_high"], dip_lbl, f_note, dip_col)

            # ── Col 5: 52W Low ────────────────────────────────────────────────
            low_str = f"Rs.{low_52w:,.2f}"
            _draw_text_right(draw, COL_X["low52w"], row_y_sym,
                             COL_W["low52w"], low_str, f_data, C_SUBTEXT)
            # % above 52W low (how far from bottom)
            pfl_str = f"+{pct_from_low:.1f}% from low"
            _draw_text_right(draw, COL_X["low52w"], row_y_name,
                             COL_W["low52w"], pfl_str, f_note, C_SUBTEXT)

            # ── Col 6: Day Change % ───────────────────────────────────────────
            day_col = _day_chg_color(p_change)
            day_str = f"{p_change:+.2f}%"
            _draw_text_centered(draw, COL_X["day_chg"], row_y_sym,
                                COL_W["day_chg"], day_str, f_data_b, day_col)
            # Day high/low
            dhl_str = f"H:{q['day_high']:,.0f} L:{q['day_low']:,.0f}"
            _draw_text_centered(draw, COL_X["day_chg"], row_y_name,
                                COL_W["day_chg"], dhl_str, f_note, C_SUBTEXT)

            # ── Col 7: 52W Flag ───────────────────────────────────────────────
            if new_52w_high:
                flag_text  = "NEW 52W HIGH"
                flag_color = C_GOLD
                # Draw a small badge
                fx = COL_X["flag"]
                fw = COL_W["flag"] - 4
                draw.rectangle([(fx, y + 10), (fx + fw, y + 28)],
                               fill=(60, 50, 0))
                draw.rectangle([(fx, y + 10), (fx + fw, y + 28)],
                               outline=C_GOLD, width=1)
                _draw_text_centered(draw, fx, y + 14, fw,
                                    flag_text, f_flag, C_GOLD)
            elif new_52w_low:
                flag_text  = "NEW 52W LOW"
                flag_color = C_RED
                fx = COL_X["flag"]
                fw = COL_W["flag"] - 4
                draw.rectangle([(fx, y + 10), (fx + fw, y + 28)],
                               fill=(60, 0, 0))
                draw.rectangle([(fx, y + 10), (fx + fw, y + 28)],
                               outline=C_RED, width=1)
                _draw_text_centered(draw, fx, y + 14, fw,
                                    flag_text, f_flag, C_RED)

            y += H_STOCK_ROW

        y += H_SECTOR_GAP

    # ── Footer ────────────────────────────────────────────────────────────────
    draw.rectangle([(0, y), (IMG_W, y + H_FOOTER)], fill=C_CARD)
    draw.rectangle([(0, y), (IMG_W, y + 2)], fill=C_BORDER)

    # Dip guide
    guide_items = [
        ("< 5%  = NEAR PEAK",   C_GREEN),
        ("5-9%  = MINOR DIP",   C_YELLOW),
        ("10-14% = MEDIUM DIP", C_ORANGE),
        ("15-19% = DEEP DIP",   C_RED),
        ("20%+  = CRASH ZONE",  C_RED),
    ]
    gx = PAD
    gy = y + 10
    for g_text, g_color in guide_items:
        draw.text((gx, gy), g_text, font=f_note, fill=g_color)
        gx += _text_w(draw, g_text, f_note) + 18

    # Disclaimer
    disc = "Data via NSE India (official). Not financial advice. Educational purpose only."
    dw2  = _text_w(draw, disc, f_note)
    draw.text(((IMG_W - dw2) // 2, y + 32), disc, font=f_note, fill=C_SUBTEXT)

    # ── Convert to bytes ──────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()


# ── Build Plain-text Fallback ─────────────────────────────────────────────────
def build_text_message(quotes: dict) -> str:
    ist  = pytz.timezone("Asia/Kolkata")
    now  = datetime.now(ist)
    date_str = now.strftime("%d %b %Y  |  %I:%M %p IST")

    lines = [
        "=" * 50,
        "  WISHLIST STOCK TRACKER",
        f"  {date_str}",
        "=" * 50,
    ]

    for sec in WISHLIST_SECTORS:
        lines.append(f"\n{sec['sector']}")
        lines.append("-" * 40)
        for stk in sec["stocks"]:
            sym  = stk["symbol"]
            name = stk["name"]
            note = stk.get("note", "")
            q    = quotes.get(sym, {})

            if q.get("error"):
                lines.append(f"  {sym} ({name}): DATA UNAVAILABLE")
                continue

            pct_h = q["pct_from_high"]
            lbl   = _dip_label(pct_h)
            flag  = ""
            if q["new_52w_high"]: flag = " [NEW 52W HIGH!]"
            if q["new_52w_low"]:  flag = " [NEW 52W LOW!]"
            note_str = f" [{note}]" if note else ""

            lines.append(
                f"  {sym}{note_str}: Rs.{q['last_price']:,.2f} | "
                f"52W H: Rs.{q['high_52w']:,.2f} ({pct_h:+.2f}% {lbl}) | "
                f"52W L: Rs.{q['low_52w']:,.2f} | "
                f"Day: {q['p_change']:+.2f}%{flag}"
            )

    lines += [
        "\n" + "=" * 50,
        "Data via NSE India. Not financial advice.",
        "=" * 50,
    ]
    return "\n".join(lines)


# ── Telegram Sender ───────────────────────────────────────────────────────────
def send_telegram_photo(bot_token: str, chat_id: str, image_bytes: bytes,
                        caption: str = "") -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("wishlist.png", image_bytes, "image/png")},
            timeout=60,
        )
        resp.raise_for_status()
        print(f"  Sent photo to {chat_id}")
        return True
    except Exception as e:
        print(f"  WARNING: Failed to send photo to {chat_id}: {e}")
        return False


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"  Sent text to {chat_id}")
        return True
    except Exception as e:
        print(f"  WARNING: Failed to send message to {chat_id}: {e}")
        return False


def notify_all(bot_token: str, chat_ids_str: str,
               image_bytes, text_msg: str) -> None:
    """Send image (or text fallback) to all configured chat IDs."""
    chat_ids = [c.strip() for c in chat_ids_str.split(",") if c.strip()]
    ist  = pytz.timezone("Asia/Kolkata")
    now  = datetime.now(ist)
    caption = (
        f"<b>Wishlist Stock Tracker</b>\n"
        f"{now.strftime('%d %b %Y  |  %I:%M %p IST')}\n"
        f"Sector-wise 52W High/Low Analysis"
    )

    for chat_id in chat_ids:
        if image_bytes and PIL_AVAILABLE:
            ok = send_telegram_photo(bot_token, chat_id, image_bytes, caption)
            if not ok:
                send_telegram_message(bot_token, chat_id, text_msg)
        else:
            send_telegram_message(bot_token, chat_id, text_msg)
        time.sleep(1)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
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
            "WISHLIST_TELEGRAM_CHAT_IDS environment variable not set.\n"
            "Add it in GitHub → Settings → Secrets and variables → Actions."
        )

    # ── Build NSE session ─────────────────────────────────────────────────────
    print("Step 1: Building NSE session...")
    session = build_nse_session()
    print("  NSE session ready.\n")

    # ── Fetch all stock quotes ─────────────────────────────────────────────────
    print("Step 2: Fetching stock quotes from NSE...")
    quotes = fetch_all_wishlist_data(session)
    print(f"  Fetched {len(quotes)} unique symbols.\n")

    # ── Build image ───────────────────────────────────────────────────────────
    image_bytes = None
    if PIL_AVAILABLE:
        print("Step 3: Building sector-wise infographic...")
        try:
            image_bytes = build_wishlist_image(quotes)
            print(f"  Image built: {len(image_bytes):,} bytes\n")
        except Exception as e:
            print(f"  WARNING: Image build failed: {e}\n")

    # ── Build text fallback ───────────────────────────────────────────────────
    text_msg = build_text_message(quotes)

    # ── Send to Telegram ──────────────────────────────────────────────────────
    print("Step 4: Sending to Telegram...")
    notify_all(bot_token, chat_ids_str, image_bytes, text_msg)
    print("\nDone!")


if __name__ == "__main__":
    main()
