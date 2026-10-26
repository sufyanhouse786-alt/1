"""Backtest strategy.SETUPS on cached 1-minute bars. Usage: backtest.py m1.json"""
import itertools, json, sys
import strategy as S

COST_PIPS = 0.8  # spread + $6/lot round-trip commission + slippage
rows = S.to_rows(json.load(open(sys.argv[1])))
days = {}
for r in rows:
    days.setdefault(r[0].date(), []).append(r)


def run(cfg):
    res = []
    for d, day in sorted(days.items()):
        if d.weekday() >= 5 or d == max(days):
            continue
        st, inf = S.signal(day, cfg)
        if st != "triggered":
            continue
        side, e, sl, tp = inf["side"], inf["entry"], inf["stop"], inf["target"]
        risk = abs(e - sl)
        R = None
        for r in day[inf["index"] + 1:]:
            if S.minute(r[0]) >= S.flat_at(d):
                R = ((r[1] - e) if side == "BUY" else (e - r[1])) / risk
                break
            if (r[3] <= sl) if side == "BUY" else (r[2] >= sl):
                R = -1; break
            if (r[2] >= tp) if side == "BUY" else (r[3] <= tp):
                R = cfg["target_r"]; break
        if R is None:
            continue
        res.append(R - COST_PIPS * S.PIP / risk)
    return res


print("%-12s %-4s %-4s %4s %5s %7s %7s" % ("setup", "stop", "tgt", "n", "win%", "avgR", "totR"))
for name, base in S.SETUPS.items():
    for stop, tr in itertools.product(["mid", "far"], [1.0, 1.5, 2.0]):
        cfg = dict(base, stop=stop, target_r=tr)
        r = run(cfg)
        if r:
            print("%-12s %-4s %-4.1f %4d %5.0f %+7.2f %+7.2f" % (name, stop, tr, len(r),
                  100 * sum(x > 0 for x in r) / len(r), sum(r) / len(r), sum(r)))
