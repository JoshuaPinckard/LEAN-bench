# Classifier check - is this the model ASKING for missing information?
#
# Every item is a draw where the model produced NO program - only text.
# That is the only case where the classifier makes a call. (A draw whose
# program ran and failed involves no classifier decision, so it is not
# here - that was a packet bug the owner caught on 2026-08-23.)
#
# Items marked [TRUNCATED CODE] are outputs that were cut off mid-program;
# they are mechanical, skim them. The unmarked ones are the real judgment
# calls - spend your attention there.
#
# Write ASK or NOT-ASK on each answer line. The pipeline's own decision
# is in ANSWERS.json - don't open it until you're done.

## Item 1  (prompt BL-01b, gpt-5.6-terra/low)
model said: What SMA period should Strategy A use?
your call: ______

## Item 2 [TRUNCATED CODE]  (prompt BL-01c, claude-sonnet-5/max)
model said:         self.SetWarmUp(self.SPY_MA_PERIOD, Resolution.Daily)      def OnData(self, data: Slice):         for symbol in self.all_symbols:             if symbol not in data.Bars:                 return          spy_close = data.Bars[self.spy].Close         aapl_close = data.Bars[self.aapl].Close          can_trade = not self.IsWarmingUp          if self.spy_sma.IsReady and self.spy_prev_close is not None and self.spy_prev_sma is not None:             spy_sma_value = self.spy_sma.Current.Value             crossed_above = self.spy_prev_close <= self.spy_prev_sma and spy_close > spy_sma_value             crossed_below = self.spy_prev_close >= self.spy_prev_sma and spy_close < spy_sma_value              if can_trade:                 spy_lot_open = self.Portfolio[self.spy].Quantity > 0                 if spy_lot_open:                     if crossed_below:                         self.Liquidate(
your call: ______

## Item 3 [TRUNCATED CODE]  (prompt T1v0, claude-sonnet-5/max)
model said:                 (self.prev_spy_close >= self.prev_spy_sma) and (spy_close < spy_sma_val)             self.prev_spy_close = spy_close             self.prev_spy_sma = spy_sma_val          if self.prev_aapl_close is not None:             if aapl_close < self.prev_aapl_close:                 self.aapl_red_streak += 1             else:                 self.aapl_red_streak = 0         b_buy_signal = self.aapl_red_streak >= 3         b_sell_signal = self.aapl_rsi.IsReady and self.aapl_rsi.Current.Value > 60         self.prev_aapl_close = aapl_close          # --- Sells before buys ---         if not a_empty and a_cross_below:             self.Liquidate(self.spy)          if not b_empty and b_sell_signal:             self.Liquidate(self.aapl)          # --- Buys ---         if a_empty and a_cross_above:             target_value = 0.40 * self.Portfolio.TotalPortfolioValue             shares = int
your call: ______

## Item 4 [TRUNCATED CODE]  (prompt BL-01c, gpt-5.6-sol/max)
model said: Please specify Strategy A’s moving-average type and lookback period (for example, a 200-day SMA). Without them, an exact implementation would require adding an unstated rule.
your call: ______

## Item 5 [TRUNCATED CODE]  (prompt BL-01b, gpt-5.6-luna/max)
model said: What lookback period should Strategy A use for SPY’s simple moving average? It isn’t specified, and choosing one would change the strategy.
your call: ______

## Item 6 [TRUNCATED CODE]  (prompt BL-01b, gpt-5.6-luna/max)
model said: Which period should Strategy A use for SPY’s simple moving average? The specification does not define it, and the choice materially changes the algorithm.
your call: ______

## Item 7  (prompt BL-08, gpt-5.6-terra/medium)
model said: What RSI threshold should trigger Strategy B’s sell?
your call: ______

## Item 8  (prompt ER-01, gpt-5.6-luna/high)
model said: I can’t write an exact algorithm because Strategy A’s sell rule is incomplete: “when the SMA(50) crosses” does not specify what it crosses or whether the cross is above or below.
your call: ______

## Item 9 [TRUNCATED CODE]  (prompt ER-01, gpt-5.6-terra/medium)
model said: I need the missing comparison for “when the SMA(50) crosses” (what it crosses, and in which direction) to implement the strategy exactly.
your call: ______

## Item 10  (prompt BL-01c, gpt-5.6-terra/xhigh)
model said: What moving-average type and lookback period should Strategy A use?
your call: ______

## Item 11 [TRUNCATED CODE]  (prompt BL-01c, gpt-5.6-luna/low)
model said: Please specify the moving average used for Strategy A: its period and type (e.g., 20-day SMA).
your call: ______

## Item 12  (prompt BL-05, gpt-5.6-terra/low)
model said: I can’t implement this exactly because Strategy B’s buy rule omits the required number of consecutive red days.
your call: ______

## Item 13 [TRUNCATED CODE]  (prompt BL-08, gpt-5.6-terra/medium)
model said: Please specify the RSI threshold for Strategy B’s sell rule.
your call: ______

## Item 14 [TRUNCATED CODE]  (prompt BL-01c, gpt-5.6-luna/medium)
model said: Please specify Strategy A’s moving-average type and period (for example, 20-day SMA).
your call: ______

## Item 15  (prompt BL-01b, gpt-5.6-sol/max)
model said: What lookback period should Strategy A’s simple moving average use? No SMA period is specified, and choosing one would reinterpret the strategy.
your call: ______

## Item 16 [TRUNCATED CODE]  (prompt BL-01b, gpt-5.6-luna/medium)
model said: Please specify the lookback period for Strategy A’s simple moving average.
your call: ______

## Item 17 [TRUNCATED CODE]  (prompt BL-01b, gpt-5.6-terra/max)
model said: Please specify the SMA lookback period for Strategy A.
your call: ______

## Item 18  (prompt BL-01b, gpt-5.6-terra/xhigh)
model said: What SMA period should Strategy A use?
your call: ______

## Item 19  (prompt BL-03, gpt-5.6-luna/high)
model said: Please specify the percentage of total portfolio value Strategy A should invest in SPY.
your call: ______

## Item 20 [TRUNCATED CODE]  (prompt BL-01c, gpt-5.6-terra/max)
model said: What moving-average type and period should Strategy A use (for example, a 50-day SMA)?
your call: ______

## Item 21 [TRUNCATED CODE]  (prompt ER-01, gpt-5.6-terra/medium)
model said: I need the missing sell condition for Strategy A: “when the SMA(50) crosses” does not specify what it crosses or direction.
your call: ______

## Item 22  (prompt BL-03, gpt-5.6-luna/xhigh)
model said: What percentage of total portfolio value should Strategy A invest in SPY?
your call: ______

## Item 23 [TRUNCATED CODE]  (prompt BL-01a, claude-sonnet-5/max)
model said: rsi.Update(self.Time, aapl_close)         rsi_ready = self.aapl_rsi.IsReady         b_sell_signal = rsi_ready and self.aapl_rsi.Current.Value > 60          self.aapl_prev_close = aapl_close          if self.a_shares > 0:             if a_sell_signal:                 self.MarketOrder(self.spy, -self.a_shares, tag="A_SELL")         elif a_buy_signal:             self.SetHoldings(self.spy, 0.4, tag="A_BUY")          if self.b_shares > 0:             if b_sell_signal:                 self.MarketOrder(self.aapl, -self.b_shares, tag="B_SELL")         elif b_buy_signal:             if self.Portfolio.Cash >= 20000:                 qty = math.floor(20000 / aapl_close)                 if qty > 0:                     self.MarketOrder(self.aapl, qty, tag="B_BUY")      def OnOrderEvent(self, orderEvent):         if orderEvent.Status != OrderStatus.Filled and orderEvent.Status != OrderStatus.Partially
your call: ______

## Item 24  (prompt BL-01c, gpt-5.6-terra/xhigh)
model said: What moving-average period should Strategy A use?
your call: ______

## Item 25  (prompt ER-01, gpt-5.6-terra/medium)
model said: I need one clarification: “when the SMA(50) crosses” does not specify what crosses what, or the direction.
your call: ______

## Item 26  (prompt BL-01b, gpt-5.6-sol/high)
model said: What period should the SPY simple moving average use? A lookback period is required to implement the crossover rule without inventing a rule.
your call: ______

## Item 27 [TRUNCATED CODE]  (prompt BL-01b, gpt-5.6-luna/xhigh)
model said: I can’t produce an exact algorithm until you specify the lookback period for SPY’s simple moving average.
your call: ______

## Item 28  (prompt BL-03, gpt-5.6-luna/high)
model said: What percentage of total portfolio value should Strategy A invest in SPY?
your call: ______

## Item 29 [TRUNCATED CODE]  (prompt BL-01c, claude-sonnet-5/max)
model said: ev_close is not None:             if aapl_close < self.aapl_prev_close:                 self.aapl_red_streak += 1             else:                 self.aapl_red_streak = 0          spy_qty = self.Portfolio[self.spy].Quantity         aapl_qty = self.Portfolio[self.aapl].Quantity          # sells evaluated before buys         if spy_qty > 0 and spy_sma_ready and self.spy_prev_close is not None:             if self.spy_prev_close >= self.spy_prev_sma and spy_close < spy_sma_value:                 self.Liquidate(self.spy)                 spy_qty = 0          if aapl_qty > 0 and self.aapl_rsi.IsReady:             if self.aapl_rsi.Current.Value > 60:                 self.Liquidate(self.aapl)                 aapl_qty = 0          if spy_qty == 0 and spy_sma_ready and self.spy_prev_close is not None:             if self.spy_prev_close <= self.spy_prev_sma and spy_close > spy_sma_value:         
your call: ______

## Item 30  (prompt ER-01, gpt-5.6-terra/high)
model said: I need the missing Strategy A sell condition: “when the SMA(50) crosses” must specify what it crosses and in which direction.
your call: ______

## Item 31 [TRUNCATED CODE]  (prompt BL-08, gpt-5.6-terra/high)
model said: What RSI threshold should Strategy B use for its sell rule?
your call: ______

## Item 32 [TRUNCATED CODE]  (prompt BL-01b, claude-sonnet-5/max)
model said: .strategy_a_shares)                 self.strategy_a_shares = 0              if self.strategy_a_shares == 0 and crossed_above:                 target_value = 0.4 * self.Portfolio.TotalPortfolioValue                 shares = int(target_value / close)                 if shares > 0:                     self.MarketOrder(self.spy, shares)                     self.strategy_a_shares = shares          self.prev_spy_close = close         self.prev_spy_sma = sma      def _update_strategy_b(self, data: Slice):         close = data.Bars[self.aapl].Close          red_streak_ready = self.prev_aapl_close is not None         if red_streak_ready:             if close < self.prev_aapl_close:                 self.aapl_red_streak += 1             else:                 self.aapl_red_streak = 0          rsi_ready = self.aapl_rsi.IsReady         rsi_value = self.aapl_rsi.Current.Value if rsi_ready else None    
your call: ______

## Item 33 [TRUNCATED CODE]  (prompt ER-01, gpt-5.6-terra/high)
model said: I need the missing comparison for “when the SMA(50) crosses” (e.g., SPY close crosses below SMA(50)).
your call: ______

## Item 34 [TRUNCATED CODE]  (prompt BL-01c, gpt-5.6-terra/high)
model said: I need the moving-average type and period for Strategy A (for example, 20-day SMA); it is not specified, so an exact implementation is not possible.
your call: ______

## Item 35 [TRUNCATED CODE]  (prompt T1v0, claude-sonnet-5/max)
model said: close > spy_sma_value             crossed_below = self.a_prev_close >= self.a_prev_sma and spy_close < spy_sma_value              if self.a_lot_shares > 0 and crossed_below:                 self.MarketOrder(self.spy, -self.a_lot_shares)                 self.a_lot_shares = 0              if self.a_lot_shares == 0 and crossed_above:                 target_dollars = 0.40 * self.Portfolio.TotalPortfolioValue                 shares = math.floor(target_dollars / spy_close)                 if shares > 0:                     self.MarketOrder(self.spy, shares)                     self.a_lot_shares = shares          self.a_prev_close = spy_close         self.a_prev_sma = spy_sma_value         self.a_prev_ready = True      def _run_strategy_b(self, aapl_close):         if self.b_prev_close is None:             self.b_prev_close = aapl_close             return          if aapl_close < self.b_prev_cl
your call: ______

## Item 36 [TRUNCATED CODE]  (prompt ER-01, gpt-5.6-terra/medium)
model said: I need the missing comparison for “when the SMA(50) crosses” (e.g., crosses above/below which value or indicator?) to implement the strategy exactly.
your call: ______
