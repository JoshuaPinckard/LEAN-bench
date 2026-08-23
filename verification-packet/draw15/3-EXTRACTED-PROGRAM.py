from AlgorithmImports import *


class IndependentDailyStrategies(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2006, 1, 3)
        self.SetEndDate(2015, 12, 31)
        self.SetCash(1_000_000)

        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol
        self.ibm = self.AddEquity("IBM", Resolution.Daily).Symbol
        self.bac = self.AddEquity("BAC", Resolution.Daily).Symbol
        self.aig = self.AddEquity("AIG", Resolution.Daily).Symbol

        self.symbols = [self.spy, self.aapl, self.ibm, self.bac, self.aig]

        self.spy_sma = self.SMA(self.spy, 100, Resolution.Daily)
        self.aapl_rsi = self.RSI(
            self.aapl, 14, MovingAverageType.Wilders, Resolution.Daily
        )

        self.SetWarmUp(101, Resolution.Daily)

        self.previous_spy_close = None
        self.previous_spy_sma = None
        self.previous_aapl_close = None
        self.aapl_red_streak = 0

    def OnData(self, data: Slice):
        has_spy_bar = data.Bars.ContainsKey(self.spy)
        has_aapl_bar = data.Bars.ContainsKey(self.aapl)
        has_all_bars = all(data.Bars.ContainsKey(symbol) for symbol in self.symbols)

        current_spy_close = data.Bars[self.spy].Close if has_spy_bar else None
        current_aapl_close = data.Bars[self.aapl].Close if has_aapl_bar else None

        if (
            has_all_bars
            and not self.IsWarmingUp
            and self.spy_sma.IsReady
            and self.aapl_rsi.IsReady
            and self.previous_spy_close is not None
            and self.previous_spy_sma is not None
        ):
            spy_crosses_above = (
                self.previous_spy_close <= self.previous_spy_sma
                and current_spy_close > self.spy_sma.Current.Value
            )
            spy_crosses_below = (
                self.previous_spy_close >= self.previous_spy_sma
                and current_spy_close < self.spy_sma.Current.Value
            )

            if self.Portfolio[self.spy].Quantity != 0:
                if spy_crosses_below:
                    self.Liquidate(self.spy)
            elif spy_crosses_above:
                self.SetHoldings(self.spy, 0.40)

            if self.Portfolio[self.aapl].Quantity != 0:
                if self.aapl_rsi.Current.Value > 60:
                    self.Liquidate(self.aapl)
            elif self.aapl_red_streak >= 3:
                if self.Portfolio.Cash >= 20_000:
                    quantity = int(20_000 // current_aapl_close)
                    if quantity > 0:
                        self.MarketOrder(self.aapl, quantity)

        if has_aapl_bar:
            if (
                self.previous_aapl_close is not None
                and current_aapl_close < self.previous_aapl_close
            ):
                self.aapl_red_streak += 1
            else:
                self.aapl_red_streak = 0

            self.previous_aapl_close = current_aapl_close

        if has_spy_bar:
            self.previous_spy_close = current_spy_close
            if self.spy_sma.IsReady:
                self.previous_spy_sma = self.spy_sma.Current.Value
