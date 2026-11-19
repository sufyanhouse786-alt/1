# EUR/USD Trading Routine — Rulebook

Automated routine run by Claude on the cTrader **demo** account (IC Markets).
Every run starts from scratch and uses the cTrader account itself as its memory:
open positions, pending orders and deal history. All times below are **London time**.

## Schedule

| Task | When (London, Mon–Fri) | Purpose |
|---|---|---|
| Trading run | 07:05, 08:05, 09:05, 10:05, 13:05, 14:05, 15:05, 16:05 | Scan setups, place or manage orders |
| Weekly review | Friday 17:10 | Weekly stats, setup scorecard, rule breaks |

Runs happen once an hour, so entries are placed as **pending STOP or LIMIT orders with stop loss and
take profit attached on the server**. The broker then executes them between runs.

## Instrument facts
- Symbol `EURUSD` (symbolId 1), 5 digits, 1 pip = 0.00010.
- Prices from `get_spot_prices` and `get_trendbars` are integers: divide by 100000.
- Order prices are normal display prices, e.g. 1.10063.
- Volume: 1 lot = 10,000,000 volume units and 0.01 lot = 100,000. Round **down** to the symbol's volume step.
- Account currency is USD, so pip value is $10 per lot.

## Risk rules (hard limits)
- **Risk per trade: 0.5% of balance.** S3 risks 0.25%.
  - lots = (balance × risk%) ÷ (stop_pips × 10); volume = lots × 10,000,000, rounded down.
- **1R** = 0.5% of the balance at the start of the day.
- **Daily stop:** no new orders once today's realised P&L is ≤ −2R, or after 2 losing trades in a row today.
- **Weekly stop:** no new orders once this week's realised P&L is ≤ −5R.
- **Max 3 new trades per day.** Filled positions count; pending orders count too while they're live.
- **Max 1 open position at a time.**
- Minimum reward:risk is 1.5. The take profit must not sit beyond a major opposing level.
- **Never widen a stop.** At +1R, move the stop to break-even plus 1 pip.
- Skip if spread > 1.5 pips or stop < 5 pips or stop > 30 pips.

## Trading windows
- New orders only between **07:00–11:00** and **13:00–16:00**.
- The 16:05 run places nothing new. It cancels all pending orders and closes any position whose stop isn't
  at break-even or better. On Friday it closes **everything**.

## News filter
- Each run checks today's economic calendar for high-impact USD or EUR events (NFP, CPI, FOMC, ECB, PCE,
  GDP, ISM, retail sales).
- No new orders from 30 minutes before to 30 minutes after an event. Pending orders that could trigger
  inside that window are cancelled.
- No new trades on FOMC or ECB decision days after 12:00.
- **If the calendar can't be checked:** place no new orders from 12:30–14:30 on any day, and none at all
  on the first Friday of the month.

## Setups

### S1 — Trend pullback (main)
1. **H4 bias:** close above a rising 50 EMA, plus the last two swing highs and lows rising, means long bias.
   The mirror image means short bias. Anything else means no S1.
2. **Zone (H1):** price pulls back into the 20–50 EMA band **and** a previous breakout or swing level.
3. **Trigger (M15, latest closed bar):** a bullish engulfing or pin bar for longs (bearish for shorts), or a
   break of the pullback's minor structure.
4. **Order:** STOP order 1 pip beyond the trigger bar's high (low for shorts), expiring in 2 hours.
   Stop loss goes beyond the pullback swing plus 2 pips. Take profit is the greater of 2R and the last
   H4 swing high (low), provided at least 2R is reachable.

### S2 — London breakout of the Asian range (07:05 run only)
1. Asian range = high and low of M15 bars from 00:00 to 07:00 London.
2. Valid only if range height < 40% of the 14-day D1 ATR **and** the H4 bias is clear. Only trade **in
   the bias direction**, so there's never a pair of orders needing one-cancels-other logic.
3. **Order:** STOP order 1 pip beyond the range edge on the bias side. Stop loss at the range midpoint.
   Take profit at 1.5× the range height from entry. Expiry at 10:30 London.

### S3 — Failed break of the previous day's high or low (0.25% risk)
1. The latest closed M15 bar, or the one before it, wicked beyond yesterday's high (low) and **closed
   back inside** yesterday's range.
2. **Order:** MARKET in the reversal direction. Stop loss is the wick extreme plus 2 pips. Take profit
   is the midpoint of yesterday's range, which must be at least 1.5R away.
3. Not allowed against a strong H4 trend: if price is more than 1× D1 ATR away from the H4 50 EMA, skip.

## Order tagging (the journal)
Every order uses:
- `label`: `eurusd-routine`
- `clientOrderId`: `YYYYMMDD-HHMM-S1` (or S2, S3); unique per order
- `comment`: setup, direction, stop in pips, planned R, e.g. `S1 long stop14.2p tp2.0R bias H4 up`

## Each run (in order)
1. `get_session_status`. If the session isn't `demo` and `trading`, **stop and report. Never trade live.**
2. `get_balance`, `get_positions`, today's and this week's `get_deals` → calculate today's R, this week's R,
   losing streak and trade count.
3. Manage what's open: move to break-even at +1R, cancel stale or news-conflicting pending orders, and
   apply the 16:05 rules.
4. If any limit is hit, or it's outside a window or in news blackout, stop scanning.
5. Otherwise check S1, S2 and S3 from trendbars (D1 ×20, H4 ×120, H1 ×120, M15 ×100) and place **at most
   one** order. If several setups qualify, priority is S2 (07:05 only), then S1, then S3.
6. Finish with a short summary: account state, R today and this week, the decision and why, and every
   order placed, changed or cancelled.
