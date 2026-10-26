"""EURUSD 1-minute breakout bot for a cTrader DEMO account.

Runs 09:00-17:00 PKT, checks every minute, takes at most one trade a day
without asking (the user's standing instruction, demo account), always with a
stop-loss and take-profit, and closes anything still open at 17:00 PKT.

  python3 bot.py            # live loop until 17:00 PKT
  python3 bot.py --once     # one check, then exit
  touch bot/STOP            # kill switch: no new trades
"""
import json, os, sys, time, traceback
from datetime import datetime, timezone
import strategy as S
from ctrader_client import CTrader

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = "london_orb"
CFG = dict(S.SETUPS[SETUP], stop="far", target_r=1.5)
SYMBOL_ID = 1               # EURUSD
LOT_VOLUME = 10_000_000     # 1 lot = 100,000 EUR, API volume = lots x 100,000 x 100
RISK_USD = float(os.environ.get("BOT_RISK_USD", "100"))  # max loss per trade at the stop
MAX_LOTS = 5.0
LABEL = "eurusd-bot"
START_PKT, END_PKT = 9 * 60, 17 * 60


def log(*a):
    now = datetime.now(S.PKT)
    line = now.strftime("%Y-%m-%d %H:%M:%S PKT ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
    with open(os.path.join(HERE, "logs", now.strftime("%Y-%m-%d") + ".log"), "a") as f:
        f.write(line + "\n")


def state_path(day):
    return os.path.join(HERE, "logs", "state-%s.json" % day)


def load_state(day):
    try:
        return json.load(open(state_path(day)))
    except (OSError, ValueError):
        return {}


def save_state(day, st):
    os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
    json.dump(st, open(state_path(day), "w"), indent=1, default=str)


def today_rows(c, now_utc):
    """Completed 1-minute bars of the current London day."""
    ldn_midnight = now_utc.astimezone(S.LDN).replace(hour=0, minute=0, second=0, microsecond=0)
    bars, t = {}, int(ldn_midnight.timestamp() * 1000)
    end = int(now_utc.timestamp() * 1000)
    while t < end:
        t2 = min(t + 16 * 3600 * 1000, end)
        r = c.call("get_trendbars", symbolId=SYMBOL_ID, period="M_1", count=1000,
                   fromTimestamp=str(t), toTimestamp=str(t2))
        for b in r.get("trendbars", []):
            bars[b["timestamp"]] = b
        t = t2
    done = [bars[k] for k in sorted(bars) if k + 60_000 <= end]  # drop the forming bar
    return S.to_rows(done)


def bot_positions(c):
    pos = c.call("get_positions").get("positions", [])
    return [p for p in pos if p.get("symbolId", SYMBOL_ID) == SYMBOL_ID and
            (p.get("label") == LABEL or LABEL in json.dumps(p))]


def lots_for(risk_pips):
    lots = int(RISK_USD / (risk_pips * 10.0) * 100) / 100.0  # ~$10 per pip per lot
    return min(lots, MAX_LOTS)


def place(c, sig, st, day):
    side, entry, stop, tgt = sig["side"], sig["entry"], sig["stop"], sig["target"]
    lots = lots_for(sig["risk_pips"])
    if lots < 0.01:
        log("SKIP: stop %.1f pips too wide for $%.0f risk" % (sig["risk_pips"], RISK_USD))
        st["done"] = "skip-size"; save_state(day, st); return
    sl_pts = int(round(abs(entry - stop) * 1e5))
    tp_pts = int(round(abs(tgt - entry) * 1e5))
    order = dict(symbolId=SYMBOL_ID, orderType="MARKET", tradeSide=side,
                 volume=int(round(lots * LOT_VOLUME)), relativeStopLoss=sl_pts,
                 relativeTakeProfit=tp_pts, label=LABEL,
                 comment="%s %s risk %.1fp" % (SETUP, side, sig["risk_pips"]))
    log("ORDER", json.dumps(order))
    st["done"] = "ordered"; st["order"] = order; st["signal"] = sig; save_state(day, st)
    res = c.call("create_order", **order)
    log("ORDER RESULT", json.dumps(res, default=str)[:1500])
    time.sleep(2)
    pos = bot_positions(c)
    if not pos:
        log("WARNING: no open bot position after the order"); return
    p = pos[0]
    pid = p.get("positionId")
    fill = p.get("price") or p.get("entryPrice") or p.get("openPrice")
    st["positionId"] = pid; save_state(day, st)
    log("POSITION", json.dumps(p, default=str)[:1500])
    if fill:  # re-anchor SL/TP to the real fill so the risk is exactly as planned
        fill = float(fill)
        risk = abs(entry - stop)
        sl = fill - risk if side == "BUY" else fill + risk
        tp = fill + CFG["target_r"] * risk if side == "BUY" else fill - CFG["target_r"] * risk
        r = c.call("amend_position", positionId=pid, stopLoss=round(sl, 5), takeProfit=round(tp, 5))
        log("AMEND SL %.5f TP %.5f" % (sl, tp), json.dumps(r, default=str)[:500])


def flatten(c, st, day):
    for p in bot_positions(c):
        r = c.call("close_position", positionId=p["positionId"], volume=p["volume"])
        log("FLAT at 17:00 PKT: closed", p["positionId"], json.dumps(r, default=str)[:500])
    st["flattened"] = True; save_state(day, st)


def check(c):
    now = datetime.now(timezone.utc)
    pkt = now.astimezone(S.PKT)
    day = now.astimezone(S.LDN).date().isoformat()
    st = load_state(day)
    if pkt.weekday() >= 5:
        return "weekend"
    m = pkt.hour * 60 + pkt.minute
    if m >= END_PKT:
        if not st.get("flattened"):
            flatten(c, st, day)
        return "closed"
    if m < START_PKT:
        return "early"
    if st.get("done"):
        return "done today (%s)" % st["done"]
    if os.path.exists(os.path.join(HERE, "STOP")):
        return "STOP file present, no new trades"
    rows = today_rows(c, now)
    status, info = S.signal(rows, CFG)
    last = rows[-1][4] if rows else None
    if status == "triggered":
        fresh = info["index"] >= len(rows) - 3  # signal bar is one of the last 3 completed
        if not fresh:
            st["done"] = "missed (signal at %s)" % info["bar_time"]; save_state(day, st)
            log("MISSED stale signal", info); return "missed"
        if bot_positions(c):
            return "position already open"
        log("TRIGGERED", {k: (str(v) if k == "bar_time" else v) for k, v in info.items()})
        place(c, info, st, day)
        return "traded"
    if status in ("expired", "skip"):
        st["done"] = status; save_state(day, st)
        log(status.upper(), {k: str(v) for k, v in info.items()})
    return "%s last %s %s" % (status, last, {k: v for k, v in info.items() if k in ("hi", "lo")})


def main():
    once = "--once" in sys.argv
    c = CTrader()
    log("bot start", SETUP, CFG, "risk $%.0f" % RISK_USD)
    last_status = None
    while True:
        try:
            s = check(c)
        except Exception:
            log("ERROR", traceback.format_exc().splitlines()[-1])
            s = "error"
            try:
                c = CTrader()
            except Exception:
                pass
        if s != last_status or datetime.now(S.PKT).minute % 15 == 0:
            log(s)
            last_status = s
        if once or s in ("closed", "weekend"):
            break
        time.sleep(60 - time.time() % 60 + 3)  # 3 s after each minute closes


if __name__ == "__main__":
    main()
