"""
NSE API diagnostic test — finds the correct working endpoint for stock data.
Tests multiple URL formats to identify what works from this machine.
"""

import sys
import time
import requests
from urllib.parse import quote as url_quote

print("=" * 65)
print("  NSE API DIAGNOSTIC TEST")
print("=" * 65)

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

# ── Build session ─────────────────────────────────────────────────────────────
print("\n[STEP 1] Building NSE session...")
session = requests.Session()
session.headers.update(NSE_HEADERS)

r = session.get("https://www.nseindia.com", timeout=30)
print(f"  Homepage:          HTTP {r.status_code}  cookies={list(session.cookies.keys())}")
time.sleep(3)

session.headers.update({"Referer": "https://www.nseindia.com/"})
r = session.get("https://www.nseindia.com/market-data/live-equity-market", timeout=30)
print(f"  Equity mkt page:   HTTP {r.status_code}  cookies={list(session.cookies.keys())}")
time.sleep(2)

# ── Test allIndices (known working endpoint) ──────────────────────────────────
print("\n[STEP 2] Testing allIndices (known working endpoint)...")
session.headers.update({"Referer": "https://www.nseindia.com/market-data/live-equity-market"})
r = session.get("https://www.nseindia.com/api/allIndices", timeout=30)
print(f"  allIndices:        HTTP {r.status_code}  body={len(r.content)} bytes")
if r.status_code == 200 and r.content:
    indices = r.json().get("data", [])
    print(f"  allIndices OK:     {len(indices)} indices returned")
    # Show first few index symbols
    for idx in indices[:5]:
        print(f"    indexSymbol: {idx.get('indexSymbol')}  last={idx.get('last')}")
else:
    print(f"  allIndices FAILED  body_preview={r.text[:200]}")
time.sleep(2)

# ── Test equity-stockIndices with multiple index names ────────────────────────
print("\n[STEP 3] Testing equity-stockIndices with various index names...")

test_indices = [
    "NIFTY 50",
    "NIFTY 100",
    "NIFTY 200",
    "NIFTY 500",
    "NIFTY SMALLCAP 250",
    "NIFTY MICROCAP 250",
]

working_indices = []
for idx_name in test_indices:
    encoded  = url_quote(idx_name)
    page_url = f"https://www.nseindia.com/market-data/live-equity-market?index={encoded}"
    api_url  = f"https://www.nseindia.com/api/equity-stockIndices?index={encoded}"

    # Visit index page first
    session.headers.update({"Referer": "https://www.nseindia.com/market-data/live-equity-market"})
    session.get(page_url, timeout=30)
    time.sleep(1)

    # Call API
    session.headers.update({"Referer": page_url})
    r = session.get(api_url, timeout=30)
    body_len = len(r.content)

    if r.status_code == 200 and body_len > 100:
        try:
            data   = r.json().get("data", [])
            stocks = [d for d in data if d.get("symbol") and d.get("symbol") != idx_name]
            print(f"  OK  {idx_name:<25} HTTP {r.status_code}  {len(stocks)} stocks")
            working_indices.append(idx_name)
        except Exception as e:
            print(f"  ERR {idx_name:<25} HTTP {r.status_code}  JSON parse failed: {e}")
    else:
        print(f"  FAIL {idx_name:<24} HTTP {r.status_code}  body={body_len} bytes  "
              f"preview={r.text[:80]!r}")
    time.sleep(2)

# ── Test quote-equity for a single stock ─────────────────────────────────────
print("\n[STEP 4] Testing quote-equity (single stock: RELIANCE)...")
session.headers.update({"Referer": "https://www.nseindia.com/get-quotes/equity?symbol=RELIANCE"})
r = session.get("https://www.nseindia.com/api/quote-equity?symbol=RELIANCE", timeout=30)
print(f"  quote-equity:      HTTP {r.status_code}  body={len(r.content)} bytes")
if r.status_code == 200 and r.content:
    pi = r.json().get("priceInfo", {})
    print(f"  RELIANCE price:    Rs.{pi.get('lastPrice')}  "
          f"52wH={pi.get('weekHighLow', {}).get('max')}  "
          f"52wL={pi.get('weekHighLow', {}).get('min')}")

# ── Test getQuotes endpoint ───────────────────────────────────────────────────
print("\n[STEP 5] Testing getQuotes endpoint (RELIANCE)...")
session.headers.update({"Referer": "https://www.nseindia.com/get-quotes/equity?symbol=RELIANCE"})
r = session.get("https://www.nseindia.com/api/getQuotes?symbol=RELIANCE&series=EQ", timeout=30)
print(f"  getQuotes:         HTTP {r.status_code}  body={len(r.content)} bytes")
if r.status_code == 200 and r.content:
    print(f"  getQuotes preview: {r.text[:200]}")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("  SUMMARY")
print("=" * 65)
if working_indices:
    print(f"  Working equity-stockIndices: {working_indices}")
    print(f"  RECOMMENDATION: Use these indices in wishlist_tracker.py")
else:
    print("  NO equity-stockIndices endpoints worked from this machine.")
    print("  NOTE: GitHub Actions (Ubuntu) may behave differently.")
    print("  The existing market_alert.py works on GitHub Actions,")
    print("  so allIndices works there. equity-stockIndices may also work.")
print("=" * 65)
