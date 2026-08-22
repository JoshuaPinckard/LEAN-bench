from AlgorithmImports import *

class ComplexityAxisAlgorithm(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2006, 1, 3)
        self.SetEndDate(2015, 12, 31)
        self.SetCash(1_000_000)

        self._tickers = ["SPY", "AAPL", "IBM", "BAC", "AIG"]
        self._symbols = {}
        for ticker in self._tickers:
            self._symbols[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol

        spy_sym = self._symbols["SPY"]
        aapl_sym = self._symbols["AAPL"]

        self._spy_sma = self.SMA(spy_sym, 100, Resolution.Daily)
        self._aapl_rsi = self.RSI(aapl_sym, 14, MovingAverageType.Wilders, Resolution.Daily)

        # Previous-bar values for cross detection and red-streak tracking
        self._prev_spy_close = None
        self._prev_spy_sma = None
        self._prev_aapl_close = None
        self._aapl_red_streak = 0

        # Each strategy tracks its own lot in shares
        self._strategy_a_shares = 0
        self._strategy_b_shares = 0

        # 150 daily bars: covers SMA(100) + extra bar for prev-SMA + margin
        self.SetWarmUp(150, Resolution.Daily)

    def OnData(self, data):
        # Skip if any subscribed ticker is missing a bar
        for symbol in self._symbols.values():
            if not data.Bars.ContainsKey(symbol):
                return

        spy_close = data.Bars[self._symbols["SPY"]].Close
        aapl_close = data.Bars[self._symbols["AAPL"]].Close

        # Update AAPL consecutive red-day count before overwriting prev close
        if self._prev_aapl_close is not None:
            if aapl_close < self._prev_aapl_close:
                self._aapl_red_streak += 1
            else:
                self._aapl_red_streak = 0

        spy_sma_today = self._spy_sma.Current.Value if self._spy_sma.IsReady else None
        aapl_rsi_today = self._aapl_rsi.Current.Value if self._aapl_rsi.IsReady else None

        # All indicators must be ready and prev values must exist before trading
        if (not self.IsWarmingUp
                and spy_sma_today is not None
                and aapl_rsi_today is not None
                and self._prev_spy_close is not None
                and self._prev_spy_sma is not None):

            # Cross: yesterday X <= Y and today X > Y  (above); mirror for below
            spy_cross_above = (self._prev_spy_close <= self._prev_spy_sma) and (spy_close > spy_sma_today)
            spy_cross_below = (self._prev_spy_close >= self._prev_spy_sma) and (spy_close < spy_sma_today)

            aapl_red_3 = self._aapl_red_streak >= 3
            aapl_rsi_above_60 = aapl_rsi_today > 60

            # ----- SELLS before BUYS -----

            # Strategy A sell: SPY crosses below 100-day SMA → liquidate entire lot
            if self._strategy_a_shares > 0 and spy_cross_below:
                self.MarketOrder(self._symbols["SPY"], -self._strategy_a_shares)
                self._strategy_a_shares = 0

            # Strategy B sell: AAPL 14-day RSI > 60 → liquidate entire lot
            if self._strategy_b_shares > 0 and aapl_rsi_above_60:
                self.MarketOrder(self._symbols["AAPL"], -self._strategy_b_shares)
                self._strategy_b_shares = 0

            # ----- BUYS -----

            # Strategy A buy: SPY crosses above 100-day SMA → invest 40% of portfolio
            if self._strategy_a_shares == 0 and spy_cross_above:
                target = self.Portfolio.TotalPortfolioValue * 0.40
                shares = int(target / spy_close)
                if shares > 0:
                    self.MarketOrder(self._symbols["SPY"], shares)
                    self._strategy_a_shares = shares

            # Strategy B buy: AAPL red 3+ consecutive days → buy $20k if cash available
            if self._strategy_b_shares == 0 and aapl_red_3:
                if self.Portfolio.Cash >= 20_000:
                    shares = int(20_000 / aapl_close)
                    if shares > 0:
                        self.MarketOrder(self._symbols["AAPL"], shares)
                        self._strategy_b_shares = shares

        # Always update previous-bar values (including during warm-up)
        self._prev_spy_close = spy_close
        self._prev_aapl_close = aapl_close
        if spy_sma_today is not None:
            self._prev_spy_sma = spy_sma_today
