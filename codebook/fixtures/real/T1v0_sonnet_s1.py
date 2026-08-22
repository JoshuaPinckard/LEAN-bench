from AlgorithmImports import *


class ComplexityAxisSpikeAlgorithm(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2006, 1, 3)
        self.SetEndDate(2015, 12, 31)
        self.SetCash(1_000_000)

        tickers = ["SPY", "AAPL", "IBM", "BAC", "AIG"]
        self.symbols = {t: self.AddEquity(t, Resolution.Daily).Symbol for t in tickers}

        self.spy_sma = self.SMA("SPY", 100, Resolution.Daily)
        self.aapl_rsi = self.RSI("AAPL", 14, MovingAverageType.Wilders, Resolution.Daily)

        # Previous-bar state needed for cross detection
        self.spy_prev_close = None
        self.spy_prev_sma = None
        self.aapl_prev_close = None

        # Rolling count of consecutive red days for AAPL
        self.aapl_red_streak = 0

        # Private lot share counts; non-zero means the lot is open
        self.strategy_a_shares = 0
        self.strategy_b_shares = 0

    def OnData(self, data):
        # If any subscribed ticker is missing a bar, skip all rule evaluation
        for sym in self.symbols.values():
            if not data.Bars.ContainsKey(sym):
                return

        spy_close = data.Bars[self.symbols["SPY"]].Close
        aapl_close = data.Bars[self.symbols["AAPL"]].Close

        # Update AAPL consecutive red day streak before evaluating rules
        if self.aapl_prev_close is not None:
            if aapl_close < self.aapl_prev_close:
                self.aapl_red_streak += 1
            else:
                self.aapl_red_streak = 0

        spy_sma_ready = self.spy_sma.IsReady
        aapl_rsi_ready = self.aapl_rsi.IsReady
        spy_sma_value = self.spy_sma.Current.Value if spy_sma_ready else None
        aapl_rsi_value = self.aapl_rsi.Current.Value if aapl_rsi_ready else None

        # ── SELLS (evaluated before buys) ────────────────────────────────────

        # Strategy A sell: SPY close crosses below its 100-day SMA
        # Cross below: yesterday close >= yesterday SMA  AND  today close < today SMA
        if (self.strategy_a_shares > 0
                and spy_sma_ready
                and self.spy_prev_close is not None
                and self.spy_prev_sma is not None):
            if self.spy_prev_close >= self.spy_prev_sma and spy_close < spy_sma_value:
                self.Liquidate(self.symbols["SPY"])
                self.strategy_a_shares = 0

        # Strategy B sell: AAPL 14-day RSI closes above 60
        if self.strategy_b_shares > 0 and aapl_rsi_ready:
            if aapl_rsi_value > 60:
                self.Liquidate(self.symbols["AAPL"])
                self.strategy_b_shares = 0

        # ── BUYS ─────────────────────────────────────────────────────────────

        # Strategy A buy: SPY close crosses above its 100-day SMA
        # Cross above: yesterday close <= yesterday SMA  AND  today close > today SMA
        if (self.strategy_a_shares == 0
                and spy_sma_ready
                and self.spy_prev_close is not None
                and self.spy_prev_sma is not None):
            if self.spy_prev_close <= self.spy_prev_sma and spy_close > spy_sma_value:
                target_value = 0.40 * self.Portfolio.TotalPortfolioValue
                shares = int(target_value / spy_close)
                if shares > 0:
                    self.MarketOrder(self.symbols["SPY"], shares)
                    self.strategy_a_shares = shares

        # Strategy B buy: AAPL has been red for 3 or more consecutive days
        # Wait for RSI(14) to be ready (RSI is used in Strategy B's sell rule)
        if (self.strategy_b_shares == 0
                and aapl_rsi_ready
                and self.aapl_red_streak >= 3):
            if self.Portfolio.Cash >= 20000:
                shares = int(20000 / aapl_close)
                if shares > 0:
                    self.MarketOrder(self.symbols["AAPL"], shares)
                    self.strategy_b_shares = shares

        # Persist end-of-bar state for cross detection on the next bar
        self.spy_prev_close = spy_close
        self.spy_prev_sma = spy_sma_value
        self.aapl_prev_close = aapl_close
