"""Shared configuration + core logic for the Wishlist Daily Tracker."""
from __future__ import annotations

import pytz

IST = pytz.timezone("Asia/Kolkata")

# ═══════════════════════════════════════════════════════════════════════════════
# STOCK CONFIGURATION (each stock belongs to exactly ONE sector)
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


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 5 — OPPORTUNITY SCORING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════════════════════
# SECTOR RETURN (equal-weighted average of the sector's member stocks)
# ═══════════════════════════════════════════════════════════════════════════════

def sector_metrics(sec: dict, quotes: dict) -> dict | None:
    """
    Equal-weighted 'sector index' return from the sector's member stocks:
      n        — number of stocks with valid data
      avg_day  — sector return for the day (average day % change)
    """
    vals = [quotes[s] for s in (stk["symbol"] for stk in sec["stocks"])
            if s in quotes and validate_stock_data(quotes[s])]
    if not vals:
        return None
    n = len(vals)
    return {
        "n":       n,
        "avg_day": round(sum(v["p_change"] for v in vals) / n, 2),
    }
