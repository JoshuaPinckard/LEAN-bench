from AlgorithmImports import *


class ExactStrategySystemAlgorithm(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2006, 1, 3)
        self.SetEndDate(2015, 12, 31)
        self.SetCash(1000000)

        self.tickers = ["SPY", "AAPL", "IBM", "BAC", "AIG"]
        self.symbols = {}
        for ticker in self.tickers:
            self.symbols[ticker] = self.AddEquity(ticker, Resolution.Daily, Market.USA, False).Symbol

        self.spy = self.symbols["SPY"]
        self.aapl = self.symbols["AAPL"]

        self.spy_sma = SimpleMovingAverage(100)
        self.aapl_rsi = RelativeStrengthIndex(14, MovingAverageType.Wilders)

        self.spy_lot = 0
        self.aapl_lot = 0

        self.spy_last_close = None
        self.spy_last_sma = None
        self.spy_prev_close_for_cross = None
        self.spy_prev_sma_for_cross = None
        self.spy_today_close = None
        self.spy_today_sma = None

        self.aapl_last_close = None
        self.aapl_red_streak = 0
        self.aapl_today_close = None

    def OnData(self, data):
        self.HandleSplits(data)
        self.UpdateMarketState(data)

        if not self.AllSubscribedBarsPresent(data):
            return

        if not self.AllRequiredHistoryReady():
            return

        spy_cross_above = (
            self.spy_prev_close_for_cross <= self.spy_prev_sma_for_cross and
            self.spy_today_close > self.spy_today_sma
        )

        spy_cross_below = (
            self.spy_prev_close_for_cross >= self.spy_prev_sma_for_cross and
            self.spy_today_close < self.spy_today_sma
        )

        aapl_red_for_3 = self.aapl_red_streak >= 3
        aapl_rsi_above_60 = float(self.aapl_rsi.Current.Value) > 60.0

        # Sells before buys.
        if self.spy_lot > 0 and spy_cross_below:
            self.MarketOrder(self.spy, -self.spy_lot, tag="Strategy A sell: SPY crossed below 100-day SMA")
            self.spy_lot = 0

        if self.aapl_lot > 0 and aapl_rsi_above_60:
            self.MarketOrder(self.aapl, -self.aapl_lot, tag="Strategy B sell: AAPL 14-day RSI above 60")
            self.aapl_lot = 0

        # Buys after all sells, in slot order.
        if self.spy_lot == 0 and spy_cross_above:
            quantity = int((0.40 * float(self.Portfolio.TotalPortfolioValue)) / self.spy_today_close)
            if quantity > 0:
                self.MarketOrder(self.spy, quantity, tag="Strategy A buy: SPY crossed above 100-day SMA")
                self.spy_lot = quantity

        if self.aapl_lot == 0 and aapl_red_for_3:
            cash_to_invest = 20000.0
            if float(self.Portfolio.Cash) >= cash_to_invest:
                quantity = int(cash_to_invest / self.aapl_today_close)
                if quantity > 0:
                    self.MarketOrder(self.aapl, quantity, tag="Strategy B buy: AAPL red for 3 consecutive days")
                    self.aapl_lot = quantity

    def HandleSplits(self, data):
        if data.Splits is None:
            return

        for symbol, split in data.Splits.items():
            if split.Type != SplitType.SplitOccurred:
                continue

            factor = float(split.SplitFactor)
            if factor == 0:
                continue

            if symbol == self.spy and self.spy_lot > 0:
                self.spy_lot = int(round(self.spy_lot / factor))

            if symbol == self.aapl and self.aapl_lot > 0:
                self.aapl_lot = int(round(self.aapl_lot / factor))

    def UpdateMarketState(self, data):
        if data.Bars is None:
            return

        if self.spy in data.Bars:
            bar = data.Bars[self.spy]

            self.spy_prev_close_for_cross = self.spy_last_close
            self.spy_prev_sma_for_cross = self.spy_last_sma if self.spy_sma.IsReady else None

            self.spy_sma.Update(IndicatorDataPoint(bar.EndTime, bar.Close))

            self.spy_last_close = float(bar.Close)
            self.spy_last_sma = float(self.spy_sma.Current.Value) if self.spy_sma.IsReady else None

            self.spy_today_close = float(bar.Close)
            self.spy_today_sma = self.spy_last_sma

        if self.aapl in data.Bars:
            bar = data.Bars[self.aapl]
            close = float(bar.Close)

            if self.aapl_last_close is None:
                self.aapl_red_streak = 0
            elif close < self.aapl_last_close:
                self.aapl_red_streak += 1
            else:
                self.aapl_red_streak = 0

            self.aapl_rsi.Update(IndicatorDataPoint(bar.EndTime, bar.Close))

            self.aapl_last_close = close
            self.aapl_today_close = close

    def AllSubscribedBarsPresent(self, data):
        if data.Bars is None:
            return False

        for symbol in self.symbols.values():
            if symbol not in data.Bars:
                return False

        return True

    def AllRequiredHistoryReady(self):
        return (
            self.spy_sma.IsReady and
            self.spy_prev_close_for_cross is not None and
            self.spy_prev_sma_for_cross is not None and
            self.spy_today_close is not None and
            self.spy_today_sma is not None and
            self.aapl_rsi.IsReady and
            self.aapl_last_close is not None and
            self.aapl_today_close is not None
        )
