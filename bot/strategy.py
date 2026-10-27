"""EURUSD 1-minute breakout rules (trader-entry / trader-exit method, adapted to forex).

Times are London local (handles UK DST). Trading window is 09:00-17:00 PKT.
  range   : bars in [range_start, range_end)
  entry   : first 1-minute CLOSE outside the range in [range_end, entry_until)
  stop    : range midpoint ("mid") or the opposite side ("far")
  target  : target_r x risk
  flat    : close anything still open at flat_at
One trade per session.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LDN = ZoneInfo("Europe/London")
PKT = ZoneInfo("Asia/Karachi")
PIP = 0.0001

SETUPS = {
    # London open breakout: 15-minute opening range
    "london_orb": dict(range_start=480, range_end=495, entry_until=600, stop="mid", target_r=1.5),
    # Asian-range breakout at the London open
    "asian_range": dict(range_start=0, range_end=480, entry_until=600, stop="mid", target_r=1.0),
}
MIN_STOP_PIPS = 4.0
MAX_STOP_PIPS = 25.0


def to_rows(bars):
    """cTrader trendbars (pipettes) -> [(london_dt, o, h, l, c)]."""
    return [(datetime.fromtimestamp(b["timestamp"] / 1000, timezone.utc).astimezone(LDN),
             b["open"] / 1e5, b["high"] / 1e5, b["low"] / 1e5, b["close"] / 1e5) for b in bars]


def minute(t):
    return t.hour * 60 + t.minute


def flat_at(day):
    """17:00 PKT expressed as London minutes for that date."""
    t = datetime(day.year, day.month, day.day, 17, 0, tzinfo=PKT).astimezone(LDN)
    return minute(t)


def signal(rows, cfg):
    """rows: one London day's completed 1-minute bars so far.
    Returns (status, info). status: 'no_range' | 'waiting' | 'expired' | 'skip' | 'triggered'."""
    rng = [r for r in rows if cfg["range_start"] <= minute(r[0]) < cfg["range_end"]]
    span = cfg["range_end"] - cfg["range_start"]
    if len(rng) < span * 0.8 or (rows and minute(rows[-1][0]) < cfg["range_end"] - 1):
        return "waiting for the range (London %02d:%02d-%02d:%02d)" % (
            cfg["range_start"] // 60, cfg["range_start"] % 60, cfg["range_end"] // 60, cfg["range_end"] % 60), {}
    hi, lo = max(r[2] for r in rng), min(r[3] for r in rng)
    mid = (hi + lo) / 2
    info = {"hi": hi, "lo": lo}
    for i, r in enumerate(rows):
        m = minute(r[0])
        if m < cfg["range_end"]:
            continue
        if m >= cfg["entry_until"]:
            return "expired", info
        side = "BUY" if r[4] > hi else "SELL" if r[4] < lo else None
        if not side:
            continue
        entry = r[4]
        stop = mid if cfg["stop"] == "mid" else (lo if side == "BUY" else hi)
        risk = abs(entry - stop)
        tgt = entry + cfg["target_r"] * risk if side == "BUY" else entry - cfg["target_r"] * risk
        info.update(side=side, entry=entry, stop=round(stop, 5), target=round(tgt, 5),
                    risk_pips=risk / PIP, bar_time=r[0], index=i)
        if not (MIN_STOP_PIPS <= risk / PIP <= MAX_STOP_PIPS):
            return "skip", info
        return "triggered", info
    return "waiting", info
