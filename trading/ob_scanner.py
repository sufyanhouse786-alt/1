"""Order block scanner for EURUSD (H1), London session.

Rules (same as the backtest):
  * Displacement candle: body >= 1.5 x ATR(14) and it closes beyond the
    20-bar high (bullish) or low (bearish).
  * Order block = last opposite-colour candle in the 5 bars before it.
      bullish OB: BUY LIMIT at OB high, stop 1 pip below OB low
      bearish OB: SELL LIMIT at OB low, stop 1 pip above OB high
  * Target = 2R. Zone lives 48 bars and is used up once price touches it.
  * Orders only live during the London session (expire 16:00 London time).
  * Stop is at least 5 pips (tiny stops get widened).
  * Risk 0.5% of balance per trade. No cap on the number of trades.

Usage:
  python3 trading/ob_scanner.py --bars bars.json --balance 9958190 \
      --money-digits 2 --bid 1.11650 --ask 1.11660 [--existing labels.txt]

  bars.json   raw output of get_trendbars (symbolId 1, H_1, count ~100)
  labels.txt  one label per line of OB orders already pending/open (to skip)

Prints a JSON list of orders ready for create_order.
"""
import argparse, json, math
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

PIP = 0.0001
SYMBOL_ID = 1
RISK_PCT = 0.5
RR = 2.0
DISP = 1.5
LIFE = 48
MIN_STOP_PIPS = 5
LONDON = ZoneInfo("Europe/London")
SESSION_START, SESSION_END = 7, 16


def find_zones(bars, now):
    # keep only closed bars
    bars = [b for b in bars if b["timestamp"] + 3600_000 <= now.timestamp() * 1000]
    O = [b["open"] / 1e5 for b in bars]; H = [b["high"] / 1e5 for b in bars]
    L = [b["low"] / 1e5 for b in bars]; C = [b["close"] / 1e5 for b in bars]
    n = len(bars)
    tr = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, n)]
    atr = [None] * n
    for i in range(13, n):
        atr[i] = sum(tr[i - 13:i + 1]) / 14
    zones = []
    for i in range(21, n):
        if n - 1 - i > LIFE:
            continue
        body = C[i] - O[i]
        if atr[i - 1] is None or abs(body) < DISP * atr[i - 1]:
            continue
        z = None
        if body > 0 and C[i] > max(H[i - 20:i]):
            j = i - 1
            while j > i - 6 and C[j] >= O[j]:
                j -= 1
            if C[j] < O[j]:
                z = dict(side="BUY", entry=H[j], stop=L[j] - PIP, ob_ts=bars[j]["timestamp"])
        elif body < 0 and C[i] < min(L[i - 20:i]):
            j = i - 1
            while j > i - 6 and C[j] <= O[j]:
                j -= 1
            if C[j] > O[j]:
                z = dict(side="SELL", entry=L[j], stop=H[j] + PIP, ob_ts=bars[j]["timestamp"])
        if not z:
            continue
        # used up if any later bar touched the entry
        later = range(i + 1, n)
        touched = any(L[k] <= z["entry"] for k in later) if z["side"] == "BUY" \
            else any(H[k] >= z["entry"] for k in later)
        if not touched:
            zones.append(z)
    return zones


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--balance", type=int, required=True)
    ap.add_argument("--money-digits", type=int, required=True)
    ap.add_argument("--bid", type=float, required=True)
    ap.add_argument("--ask", type=float, required=True)
    ap.add_argument("--existing", default=None)
    ap.add_argument("--now", default=None, help="ISO time, for testing")
    a = ap.parse_args()

    now = datetime.fromisoformat(a.now) if a.now else datetime.now(timezone.utc)
    ln = now.astimezone(LONDON)
    if ln.weekday() >= 5 or not (SESSION_START <= ln.hour < SESSION_END):
        print(json.dumps({"orders": [], "note": "outside London session"}))
        return
    expiry = ln.replace(hour=SESSION_END, minute=0, second=0, microsecond=0)
    expiry_ms = int(expiry.timestamp() * 1000)

    data = json.load(open(a.bars))
    bars = data["trendbars"] if isinstance(data, dict) else data
    existing = set()
    if a.existing:
        existing = {l.strip() for l in open(a.existing) if l.strip()}

    balance = a.balance / 10 ** a.money_digits
    risk_usd = balance * RISK_PCT / 100
    orders, skipped = [], []
    seen = set()
    for z in find_zones(bars, now):
        label = f"OB-{z['side']}-{z['ob_ts']}"
        if label in seen:
            continue
        seen.add(label)
        if label in existing:
            skipped.append({"label": label, "why": "already placed"})
            continue
        # a limit order must be on the right side of the market
        if (z["side"] == "BUY" and a.ask <= z["entry"]) or (z["side"] == "SELL" and a.bid >= z["entry"]):
            skipped.append({"label": label, "why": "price already through entry"})
            continue
        dist = abs(z["entry"] - z["stop"])
        if dist < MIN_STOP_PIPS * PIP:  # widen tiny stops (spread would eat them)
            dist = MIN_STOP_PIPS * PIP
            z["stop"] = z["entry"] - dist if z["side"] == "BUY" else z["entry"] + dist
        units = math.floor(risk_usd / dist / 1000) * 1000  # 0.01-lot steps
        if units < 1000:
            skipped.append({"label": label, "why": "size too small"})
            continue
        tp = z["entry"] + RR * dist if z["side"] == "BUY" else z["entry"] - RR * dist
        orders.append(dict(
            symbolId=SYMBOL_ID, orderType="LIMIT", tradeSide=z["side"],
            volume=units * 100, limitPrice=round(z["entry"], 5),
            stopLoss=round(z["stop"], 5), takeProfit=round(tp, 5),
            timeInForce="GOOD_TILL_DATE", expirationTimestamp=expiry_ms,
            label=label, comment=label,
            _info=dict(lots=units / 100000, stop_pips=round(dist / PIP, 1),
                       risk_usd=round(units * dist, 2))))
    print(json.dumps({"orders": orders, "skipped": skipped}, indent=1))


if __name__ == "__main__":
    main()
