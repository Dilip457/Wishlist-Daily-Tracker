"""
Quick connectivity + data sanity test for the wishlist tracker providers.

Run locally:  python test_tracker.py
(No Telegram credentials needed — delivery is not tested here.)
"""

import sys

sys.path.insert(0, ".")

from wishlist_tracker import (YahooChartAPIProvider, YahooFinanceProvider,
                               get_unique_symbols, load_cache,
                               score_opportunity, validate_stock_data)


def main() -> int:
    symbols = get_unique_symbols()
    print(f"{len(symbols)} unique symbols: {', '.join(symbols)}\n")

    print("── Primary provider (yfinance) ──")
    yf_ok, chart_ok, failed = 0, 0, []
    for sym in symbols:
        d = YahooFinanceProvider().get_stock_data(sym)
        if validate_stock_data(d):
            yf_ok += 1
            continue
        print(f"  yfinance failed for {sym} -> trying chart API fallback...")
        d = YahooChartAPIProvider().get_stock_data(sym)
        if validate_stock_data(d):
            chart_ok += 1
        else:
            failed.append(sym)

    print(f"\nyfinance OK:        {yf_ok}/{len(symbols)}")
    print(f"chart-API fallback: {chart_ok} (recovered)")
    print(f"failed:             {len(failed)} {failed or ''}")

    # Spot-check one symbol end-to-end through scoring.
    cache = load_cache()
    sym = "SBIN"
    d = YahooFinanceProvider().get_stock_data(sym)
    q = score_opportunity(d if validate_stock_data(d)
                          else cache.get("stocks", {}).get(sym, d))
    print(f"\nSpot check {sym}: price ₹{q['last_price']:.2f} "
          f"52wH ₹{q['high_52w']:.2f} 52wL ₹{q['low_52w']:.2f} "
          f"day {q['p_change']:+.2f}% from-high {q['pct_from_high']:+.2f}%")

    if failed:
        print("\nRESULT: FAIL (some symbols unavailable from every provider)")
        return 1
    print("\nRESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
