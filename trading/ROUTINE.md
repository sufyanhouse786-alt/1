# London Order Block Routine (EURUSD, demo account)

Runs every hour at :02, 07:02–15:02 London time, Monday to Friday.

## Settings
- Symbol: EURUSD (symbolId 1), H1 candles
- Risk: 0.5% of balance per trade
- Target: 2R (2x the stop distance)
- Stop: 1 pip beyond the order block candle, at least 5 pips
- No limit on how many trades are open at once
- Pending orders expire at 16:00 London time
- Every order has the label/comment `OB-<BUY|SELL>-<candle timestamp>`

## Steps each run
1. `get_trendbars` symbolId 1, period H_1, count 100. Save the JSON to a file.
2. `get_balance` (balance + moneyDigits), `get_spot_prices` [1] (bid/ask, in pipettes:
   divide by 100000).
3. `get_positions`: write every label/comment that starts with `OB-` (pending orders
   and open positions) to a labels file, one per line.
4. Run:
   ```
   python3 trading/ob_scanner.py --bars bars.json --balance <balance> \
     --money-digits <moneyDigits> --bid <bid> --ask <ask> --existing labels.txt
   ```
5. For every order in the output, call `create_order` with those exact fields
   (drop `_info`).
6. Never touch positions or orders whose label does not start with `OB-`.

## Backtest (Nov 2024 – Nov 2026, H1, London entries, 1 pip cost)
143 trades, 32% win rate, −72 pips at 2R. This is about breakeven, so it is NOT a
proven edge. Run it on demo only.
