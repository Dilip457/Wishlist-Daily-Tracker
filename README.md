# 📊 Wishlist Stock Daily Tracker

An automated daily alert system that monitors **sector-wise wishlist stocks** from NSE India and sends a single **multi-page PDF report** to a **Telegram group/channel** every weekday after market close.

Data is sourced from **Yahoo Finance** (`.NS` symbols, same numbers as nseindia.com) with layered fallbacks so a single flaky API never breaks the daily alert.

---

## 💡 What It Does

Every weekday at **6:00 PM IST** (after NSE market close), the tracker:

1. Fetches live data for all 27 wishlist stocks
2. Calculates **% below 52-week high** for each stock (the "dip" signal)
3. Detects if any stock hit a **new 52W high or low** today
4. Builds **one multi-page PDF report** — page 1 summary (dip-band distribution, data health, new 52W flags) + sector-wise tables, with each sector's **1-day sector return** shown in its header band
5. Sends the PDF to your **Telegram group/channel** via `sendDocument` (far easier to read than multiple images)

---

## 🛡 Reliability Design

| Layer | What it does |
|---|---|
| **Primary provider** | `yfinance` via `ticker.history(period="1y")` — works on yfinance 0.2.x and 1.x (`fast_info` was removed in 1.x and silently broke the old build) |
| **Retry + backoff** | Every symbol retried up to 3× (1s/2s backoff) — Yahoo's "possibly delisted" error is usually rate limiting |
| **Fallback provider** | Direct Yahoo v8 chart REST API — independent of the yfinance library, so a new yfinance release can't break the pipeline |
| **Cache** | `data/cache.json` stores the last good value per symbol; if a stock is temporarily unfetchable, the report shows its last known price marked `[CACHED]` |
| **Safe cache commit** | The workflow rebases before pushing, so concurrent runs never wedge the cache commit |

The report's caption always shows **Live X/27**, so you know at a glance whether today's numbers are fresh.

---

## 📋 Stocks Tracked (Sector-wise)

| Sector | Stocks |
|---|---|
| ALCOHOL & BREWERIES | RADICO (Radico Khaitan) |
| POWER SECTOR | TATAPOWER, CGPOWER |
| EXCHANGE PLATFORM | BSE, MCX |
| SHRIMP SECTOR | AVANTIFEED *(EXITING)* |
| AUTO SECTOR | TVSMOTOR, M&M |
| FERTILIZER SECTOR | COROMANDEL |
| CABLE SECTOR | KEI |
| HOSPITALITY SECTOR | INDHOTEL |
| PHARMA SECTOR | TORNTPHARM |
| CAPITAL GOODS SECTOR | CUMMINSIND |
| IT SECTOR | PERSISTENT |
| AUTO ANCILLARY SECTOR | UNOMINDA, SONACOMS |
| SEMICONDUCTOR SECTOR | MOSCHIP *(highly valued)* |
| SPACE SECTOR | LT, DATAPATTNS |
| DATA CENTER SECTOR | ANANTRAJ, NETWEB |
| BANKING SECTOR | SBIN, INDIANB |
| DEFENCE SECTOR | BEL |
| HOSPITAL SECTOR | APOLLOHOSP, FORTIS |
| CONSUMER DURABLES | BLUESTARCO |

> Note: every stock belongs to exactly ONE sector so the report stays unambiguous — BEL (defence electronics, with space/drone exposure) is classified under DEFENCE only.

### Sector Return

Each sector shows a **sector return** — the equal-weighted average of its member stocks' day change — in its colored header band on every report page. The Telegram caption also calls out the best and worst sector of the day.

---

### Color Coding

| Color | Signal | Meaning |
|---|---|---|
| 🟢 Green | < 5% from high | Near 52W peak — regular SIP only |
| 🟡 Yellow | 5–9% from high | Minor dip — watch closely |
| 🟠 Orange | 10–14% from high | Medium dip — consider buying |
| 🔴 Red | 15–19% from high | Deep dip — strong buy signal |
| 🔴 Dark Red | 20%+ from high | Crash zone — max opportunity |

### Special Flags

- **NEW 52W HIGH** (gold) — Stock hit a new 52-week high today
- **NEW 52W LOW** (red) — Stock hit a new 52-week low today
- **[CACHED]** (yellow) — Live fetch failed; last known price shown
- **[EXITING]** / **[highly valued]** — manual notes from the watchlist

---

## 🚀 Setup Guide

### Step 1 — Create a Telegram Group/Channel for Wishlist Alerts

1. Open Telegram → **New Group** (or **New Channel**)
2. Name it (e.g. `Wishlist Stock Alerts`)
3. Add your bot as **Admin** (enable **"Post Messages"**)
4. Get the group/channel ID by forwarding a message from it to **@userinfobot**

### Step 2 — Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Value |
|---|---|
| `WISHLIST_TELEGRAM_CHAT_IDS` | e.g. `-1001234567890` (comma-separate for multiple) |
| `TELEGRAM_BOT_TOKEN` | Your bot token |

> If `WISHLIST_TELEGRAM_CHAT_IDS` is not set, the script falls back to `TELEGRAM_CHAT_IDS`.

### Step 3 — Test It

1. Repo → **Actions** tab → **Daily Wishlist Stock Tracker** → **Run workflow**
2. Wait ~2 minutes → check Telegram for the PDF

---

## ⚙️ How It Works

```
GitHub Actions (cron: Mon–Fri 6:00 PM IST = 12:30 UTC)
      │
      ▼
wishlist_tracker.py runs
      │
      ├─→ Fetches each symbol (3 layers):
      │     1. yfinance  (retry ×3, backoff)
      │     2. Yahoo v8 chart REST API (fallback)
      │     3. data/cache.json (last good value)
      │
      ├─→ Calculates per stock:
      │     • % below 52W high  (dip signal)
      │     • % above 52W low   (recovery signal)
      │     • New 52W high/low detection
      │
      ├─→ Builds ONE multi-page PDF (reportlab):
      │     • Page 1: summary — live/cached counts,
      │       dip-band distribution with symbol lists,
      │       new 52W flags
      │     • Sector tables: price, day change, 52W
      │       high/low, % from high with dip label,
      │       day H/L, flags — each sector band shows
      │       its 1-day sector return
      │
      └─→ Sends PDF to Telegram (sendDocument)
          (plain-text message as automatic fallback)
```

---

## 🔧 Customization

### Add / Remove Stocks

Edit `WISHLIST_SECTORS` in `wishlist_tracker.py`:

```python
{
    "sector": "MY NEW SECTOR",
    "color":  (88, 166, 255),   # RGB accent color for this sector
    "stocks": [
        {"symbol": "RELIANCE",  "name": "Reliance Industries"},
        {"symbol": "HDFCBANK",  "name": "HDFC Bank", "note": "watching"},
    ],
}
```

Use the exact NSE symbol (check the URL on nseindia.com: `...?symbol=RELIANCE`).

### Change the Schedule

Edit the cron in `.github/workflows/daily_alert.yml`:

```yaml
- cron: '30 12 * * 1-5'   # 6:00 PM IST = 12:30 PM UTC
```

---

## 🕐 Schedule

| Event | Time |
|---|---|
| NSE market closes | 3:30 PM IST |
| Wishlist tracker runs | 6:00 PM IST (Mon–Fri) |
| GitHub Actions cron | `30 12 * * 1-5` (UTC) |

---

## ❓ Troubleshooting

| Issue | Likely Cause | Fix |
|---|---|---|
| Stock shows "DATA UNAVAILABLE" | Yahoo throttling or bad symbol | Run `python test_tracker.py` to verify; check symbol on nseindia.com |
| Prices show "[CACHED]" | Live fetch failed, cache used | Usually transient; if persistent, check Actions logs |
| No PDF received | reportlab missing | Check `pip install -r requirements.txt` in Actions logs |
| Bot can't post | Bot not admin | Add bot as admin with Post Messages |
| Cache commit fails | Concurrent run pushed first | Already handled via rebase; just re-run |

---

## 🛠 Tech Stack

| Component | Tool | Cost |
|---|---|---|
| Data source | Yahoo Finance (yfinance + direct REST fallback) | Free |
| Notifications | Telegram Bot API | Free |
| Scheduling & hosting | GitHub Actions | Free |
| PDF generation | reportlab | Free |
| Language | Python 3.11 | Free |

**Total cost: ₹0/month**

---

*Not financial advice. For educational purposes only. Do your own research before investing.*
