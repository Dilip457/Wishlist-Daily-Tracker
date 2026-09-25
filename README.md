# 📊 Wishlist Stock Daily Tracker

An automated daily alert system that monitors **sector-wise wishlist stocks** from NSE India and sends a formatted infographic image to a **Telegram group/channel** every weekday after market close.

Data is sourced directly from **NSE India's official API** — the same numbers shown on [nseindia.com](https://www.nseindia.com).

---

## 💡 What It Does

Every weekday at **4:30 PM IST** (after NSE market close), the tracker:

1. Fetches live data for all 27 wishlist stocks from NSE India
2. Calculates **% below 52-week high** for each stock (the "dip" signal)
3. Detects if any stock hit a **new 52W high or low** today
4. Generates a **sector-wise infographic PNG** with color-coded dip signals
5. Sends the image to your **Telegram group/channel**

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
| SPACE SECTOR | LT, BEL, DATAPATTNS |
| DRONE SECTOR | BEL |
| DATA CENTER SECTOR | ANANTRAJ, NETWEB |
| BANKING SECTOR | SBIN, INDIANB |
| DEFENCE SECTOR | BEL |
| HOSPITAL SECTOR | APOLLOHOSP, FORTIS |
| CONSUMER DURABLES | BLUESTARCO |

> Note: BEL appears in SPACE, DRONE, and DEFENCE sectors intentionally — it plays across all three themes.

---

## 📱 Sample Infographic

The daily image shows for each stock:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│              WISHLIST STOCK TRACKER                                              │
│   Sector-wise  |  52W High / Low Analysis  |  Daily Dip Monitor                 │
│                    25 Sep 2026  |  04:30 PM IST                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│ ⚡ POWER SECTOR                                                      2 stocks    │
├──────────────┬────────────┬────────────┬────────────┬────────────┬──────────────┤
│ STOCK        │ PRICE      │ 52W HIGH   │ % FROM HIGH│ 52W LOW    │ DAY CHG%     │
├──────────────┼────────────┼────────────┼────────────┼────────────┼──────────────┤
│ TATAPOWER    │ Rs.412.50  │ Rs.500.00  │ -17.50%    │ Rs.350.00  │ +1.20%       │
│ Tata Power   │            │            │ DEEP DIP   │+17.9% low  │ H:415 L:408  │
├──────────────┼────────────┼────────────┼────────────┼────────────┼──────────────┤
│ CGPOWER      │ Rs.650.00  │ Rs.800.00  │ -18.75%    │ Rs.500.00  │ -0.50%       │
│ CG Power     │            │            │ DEEP DIP   │+30.0% low  │ H:655 L:645  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Color Coding

| Color | Signal | Meaning |
|---|---|---|
| 🟢 Green | < 5% from high | Near 52W peak — regular SIP only |
| 🟡 Yellow | 5–9% from high | Minor dip — watch closely |
| 🟠 Orange | 10–14% from high | Medium dip — consider buying |
| 🔴 Red | 15–19% from high | Deep dip — strong buy signal |
| 🔴 Dark Red | 20%+ from high | Crash zone — max opportunity |

### Special Flags

- **NEW 52W HIGH** (gold badge) — Stock hit a new 52-week high today
- **NEW 52W LOW** (red badge) — Stock hit a new 52-week low today
- **[EXITING]** (red text) — Stock marked for exit from watchlist
- **[highly valued]** (yellow text) — Stock noted as richly valued

---

## 🚀 Setup Guide

### Step 1 — Create a Telegram Group/Channel for Wishlist Alerts

1. Open Telegram → **New Group** (or **New Channel**)
2. Name it (e.g. `Wishlist Stock Alerts` or `My Stock Watchlist`)
3. Add your bot as **Admin**:
   - Open the group/channel → Settings → Administrators → Add Administrator
   - Search your bot → add it → enable **"Post Messages"** → Done
4. Get the group/channel ID:
   - Forward any message from the group to **@userinfobot**
   - It replies with the chat ID (e.g. `-1001234567890`)

> If you already have a bot from the main market alert setup, you can reuse the same bot.

---

### Step 2 — Add GitHub Secret

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Value | Notes |
|---|---|---|
| `WISHLIST_TELEGRAM_CHAT_IDS` | Your group/channel ID(s) | e.g. `-1001234567890` |
| `TELEGRAM_BOT_TOKEN` | Your bot token | Same as main alert (already set) |

For multiple recipients, separate with commas:
```
-1001234567890,-1009876543210,@my_channel
```

> **Tip:** If `WISHLIST_TELEGRAM_CHAT_IDS` is not set, the script automatically falls back to `TELEGRAM_CHAT_IDS` — so you can send both alerts to the same chat.

---

### Step 3 — Test It

1. Go to your repo → **Actions** tab
2. Click **Daily Wishlist Stock Tracker** → **Run workflow** → **Run workflow**
3. Wait ~60 seconds (fetches 27 stocks) → check Telegram

---

## ⚙️ How It Works

```
GitHub Actions (cron: Mon–Fri 4:30 PM IST)
      │
      ▼
wishlist_tracker.py runs
      │
      ├─→ Builds NSE session (cookies for API access)
      │
      ├─→ Fetches quote-equity API for each unique symbol
      │         Returns: lastPrice, weekHighLow (52W H/L),
      │                  intraDayHighLow (day H/L), pChange
      │
      ├─→ Calculates for each stock:
      │         • % below 52W high  (dip signal)
      │         • % above 52W low   (recovery signal)
      │         • New 52W high/low detection
      │
      ├─→ Builds sector-wise PNG infographic (900px wide)
      │         • Dark theme, color-coded dip signals
      │         • Sector headers with accent colors
      │         • NEW 52W HIGH/LOW badges
      │
      └─→ Sends PNG to Telegram group/channel
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
},
```

### Find the Correct NSE Symbol

The `symbol` must match NSE's exact equity symbol. To verify:
1. Go to [nseindia.com](https://www.nseindia.com)
2. Search for the stock
3. The URL will show: `nseindia.com/get-quotes/equity?symbol=RELIANCE`
4. Use that exact symbol string

### Common NSE Symbols Reference

| Company | NSE Symbol |
|---|---|
| Reliance Industries | `RELIANCE` |
| HDFC Bank | `HDFCBANK` |
| Infosys | `INFY` |
| TCS | `TCS` |
| Tata Motors | `TATAMOTORS` |
| Wipro | `WIPRO` |
| Adani Enterprises | `ADANIENT` |
| Bajaj Finance | `BAJFINANCE` |
| Asian Paints | `ASIANPAINT` |
| Titan Company | `TITAN` |

### Change the Schedule

Edit the cron in `.github/workflows/wishlist_tracker.yml`:

```yaml
- cron: '00 11 * * 1-5'   # 4:30 PM IST = 11:00 AM UTC
```

Use [crontab.guru](https://crontab.guru) to calculate UTC times.

---

## 🕐 Schedule

| Event | Time |
|---|---|
| NSE market closes | 3:30 PM IST |
| Wishlist tracker runs | 4:30 PM IST (Mon–Fri) |
| GitHub Actions cron | `00 11 * * 1-5` (UTC) |

---

## ❓ Troubleshooting

| Issue | Likely Cause | Fix |
|---|---|---|
| Stock shows "DATA UNAVAILABLE" | Wrong NSE symbol | Verify symbol on nseindia.com |
| No image received | Pillow not installed | Check GitHub Actions logs |
| NSE connection failed | NSE blocked GitHub IP | Re-run workflow; usually resolves |
| Bot can't post to group | Bot not admin | Add bot as admin with Post Messages |
| `WISHLIST_TELEGRAM_CHAT_IDS` not set | Secret missing | Add secret or it falls back to `TELEGRAM_CHAT_IDS` |

---

## 📁 File Structure

```
Wishlist_Daily_Tracker/
├── wishlist_tracker.py     ← Main script
└── README.md               ← This file

.github/workflows/
└── wishlist_tracker.yml    ← GitHub Actions schedule
```

---

## 🛠 Tech Stack

| Component | Tool | Cost |
|---|---|---|
| Data source | NSE India official API | Free |
| Notifications | Telegram Bot API | Free |
| Scheduling & hosting | GitHub Actions | Free |
| Image generation | Pillow (PIL) | Free |
| Language | Python 3.11 | Free |

**Total cost: ₹0/month**

---

*Not financial advice. For educational purposes only. Do your own research before investing.*
