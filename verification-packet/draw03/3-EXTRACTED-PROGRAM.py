from AlgorithmImports import *
import math


class ParallelSmaAndRsiStrategies(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2006, 1, 3)
        self.SetEndDate(2015, 12, 31)
        self.SetCash(1_000_000)

        self.symbols = {}
        for ticker in ["SPY", "AAPL", "IBM", "BAC", "AIG"]:
            self.symbols[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol

        self.spy = self.symbols["SPY"]
        self.aapl = self.symbols["AAPL"]

        self.spy_sma = self.SMA(self.spy, 50, Resolution.Daily)
        self.aapl_rsi = self.RSI(self.aapl, 14, MovingAverageType.Wilders, Resolution.Daily)

        self.spy_close_history = RollingWindow[float](2)
        self.aapl_close_history = RollingWindow[float](2)

        self.aapl_red_streak = 0

        self.strategy_a_shares = 0
        self.strategy_b_shares = 0

    def OnData(self, data: Slice):
        for symbol in self.symbols.values():
            if not data.Bars.ContainsKey(symbol):
                return

        spy_close = data.Bars[self.spy].Close
        aapl_close = data.Bars[self.aapl].Close

        if self.aapl_close_history.Count > 0:
            if aapl_close < self.aapl_close_history[0]:
                self.aapl_red_streak += 1
            else:
                self.aapl_red_streak = 0

        history_ready = (
            self.spy_sma.IsReady and
            self.aapl_rsi.IsReady and
            self.spy_close_history.Count == 2 and
            self.aapl_close_history.Count == 1
        )

        if history_ready:
            yesterday_spy_close = self.spy_close_history[0]
            yesterday_spy_sma = self.spy_sma.Window[1].Value
            today_spy_sma = self.spy_sma.Current.Value

            spy_crosses_above_sma = (
                yesterday_spy_close <= yesterday_spy_sma and
                spy_close > today_spy_sma
            )
            spy_crosses_below_sma = (
                yesterday_spy_close >= yesterday_spy_sma and
                spy_close < today_spy_sma
            )

            if self.strategy_a_shares > 0 and spy_crosses_below_sma:
                self.MarketOrder(self.spy, -self.strategy_a_shares)
                self.strategy_a_shares = 0

            if self.strategy_b_shares > 0 and self.aapl_rsi.Current.Value > 60:
                self.MarketOrder(self.aapl, -self.strategy_b_shares)
                self.strategy_b_shares = 0

            if self.strategy_a_shares == 0 and spy_crosses_above_sma:
                shares = int(math.floor(
                    0.40 * self.Portfolio.TotalPortfolioValue / spy_close
                ))
                if shares > 0:
                    self.MarketOrder(self.spy, shares)
                    self.strategy_a_shares = shares

            if (
                self.strategy_b_shares == 0 and
                self.aapl_red_streak >= 3 and
                self.Portfolio.Cash >= 20_000
            ):
                shares = int(math.floor(20_000 / aapl_close))
                if shares > 0:
                    self.MarketOrder(self.aapl, shares)
                    self.strategy_b_shares = shares

        self.spy_close_history.Add(spy_close)
        self.aapl_close_history.Add(aapl_close)
