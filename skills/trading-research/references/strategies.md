# Strategy library
Format adapted from daily_stock_analysis (MIT). Each strategy is YAML; the agent evaluates it with tool data and outputs a score delta, entry, stop and reason. Template: assets/strategy-template.yaml.

## Core principles (apply to every long setup)
1. Strict entry: price within 5% of MA5 (don't chase).
2. Trend: MA5 > MA10 > MA20 for trend-following setups.
3. Volume must confirm the move.
4. Prefer pullbacks to moving-average support over breakouts into resistance.
5. **Negative news is a one-vote veto.**
6. Price and volume must agree.
7. Rules may relax for clear sector leaders; say so explicitly.

## Built-in setups
| id | regime | rule summary | entry / stop |
|---|---|---|---|
| shrink_pullback | uptrend | MA5>MA10>MA20; pullback to within 1% of MA5 or 2% of MA10 on volume <70% of 5-day avg; MA5 bias <2%; no negative news. +10 at MA5, +8 at MA10 with vol <0.6× | entry MA5 (alt MA10), stop MA20 |
| volume_breakout | range→trend | close above N-day high on volume ≥1.5× 20-day avg | entry breakout close, stop below breakout bar low |
| ma_golden_cross | turning | MA20 crosses above MA60 with rising volume | entry next bar, stop below MA60 |
| bottom_volume | downtrend exhaustion | long-term low + volume spike + reversal candle | stop below spike low |
| box_oscillation | range | buy near box floor, sell near ceiling, ≥2 touches each side | stop below floor |
| orb (opening range breakout) | intraday | break of first 15/30-min range with volume, after 09:45 ET | stop at OR midpoint, target 1R–2R |
| bull_flag | intraday/swing | strong pole, tight low-volume consolidation, break of flag high | stop below flag low |
| oversold_bounce | mean-reversion | RSI(14) <30 and close back above prior day low | stop under swing low |
| event_driven | any | dated catalyst (earnings, FDA, product) with defined risk | define exit before the event |
| growth_quality | position | revenue growth >20%, expanding margins, reasonable PEG | fundamentals-based invalidation |
Other named setups in daily_stock_analysis: chan_theory, dragon_head, emotion_cycle, expectation_repricing, hot_theme, one_yang_three_yin, wave_theory (China retail TA; use with care).

## Market-regime gate
Before any long setup, check the index: above its 50-day MA and the 50 above the 200 = risk-on; otherwise cut size in half or require the stricter setups only.

## Mechanical accumulation and range setups (from common bot designs)
- **Ladder / scale out-scale in:** preset sell levels on the way up and buy-back levels lower, fixed share counts. Write the levels before the first fill; no moving them intraday.
- **Grid (range):** limit buys a little below and sells a little above inside a range the user names; stop the grid on a close outside the range. Grids lose in trends: run the regime check first.
- **Sentiment-weighted DCA:** fixed schedule, buy more in extreme fear and less in extreme greed (CNN Fear & Greed or crypto equivalents). Unproven as an edge; the schedule is the point.
- **Quality dip:** only names that pass the fundamentals screen, after a market-wide selloff, with a stop on every position. Test the dip depth with rule_screen.py before using it.
- **Indicator tickets (RSI, MACD, Bollinger, VWAP pullback, 9 EMA pullback, stochastic, compression breakout):** each produces a ticket with entry, stop, target and invalidation ("no close through the line, no entry"), then goes through rule_screen.py and the permutation gates before any paper trade.

