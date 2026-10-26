"""Cache ~30 days of EURUSD 1-minute bars to a JSON file (for backtests)."""
import json, sys, time
from ctrader_client import CTrader

out = sys.argv[1]
c = CTrader()
end = int(time.time() * 1000)
start = end - 30 * 86400 * 1000
bars = {}
t = start
while t < end:
    t2 = min(t + 16 * 3600 * 1000, end)
    r = c.call("get_trendbars", symbolId=1, period="M_1", count=1000,
               fromTimestamp=str(t), toTimestamp=str(t2))
    for b in r.get("trendbars", []):
        bars[b["timestamp"]] = b
    t = t2
json.dump([bars[k] for k in sorted(bars)], open(out, "w"))
print(len(bars), "bars")
