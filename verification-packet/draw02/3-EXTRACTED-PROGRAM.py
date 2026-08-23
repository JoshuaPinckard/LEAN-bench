from AlgorithmImports import *
import math


class ExactStrategyAlgorithm(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2006, 1, 3)
        self.SetEndDate(2015, 12, 31)
        self.SetCash(1000000)

        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol
        self.ibm = self.AddEquity("IBM", Resolution.Daily).Symbol
        self.bac = self.AddEquity("BAC", Resolution.Daily).Symbol
        self.aig = self.AddEquity("AIG", Resolution.Daily).Symbol

        self.symbols = (
            self.spy,
            self.aapl,
            self.ibm,
            self.bac,
            self.aig,
        )

        self.spy_sma = self.SMA(self.spy, 100, Resolution.Daily)
        self.aapl_rsi = self.RSI(
            self.aapl,
            14,
            MovingAverageType.Wilders,
            Resolution.Daily
        )

        self.strategy_a_lot = 0
        self.strategy_b_lot = 0

        self.previous_spy_close = None
        self.previous_spy_sma = None

        self.previous_aapl_close = None
        self.aapl_red_streak = 0

    def OnData(self, data):
        bars = {}
        all_bars_present = True

        for symbol in self.symbols:
            if data.Bars.ContainsKey(symbol):
                bars[symbol] = data.Bars[symbol]
            else:
                bars[symbol] = None
                all_bars_present = False

        spy_close = None
        current_spy_sma = None
        prior_spy_close = self.previous_spy_close
        prior_spy_sma = self.previous_spy_sma

        if bars[self.spy] is not None:
            spy_close = float(bars[self.spy].Close)

            if self.spy_sma.IsReady:
                current_spy_sma = float(self.spy_sma.Current.Value)
                self.previous_spy_sma = current_spy_sma

            self.previous_spy_close = spy_close

        if bars[self.aapl] is not None:
            aapl_close = float(bars[self.aapl].Close)

            if self.previous_aapl_close is None:
                self.aapl_red_streak = 0
            elif aapl_close < self.previous_aapl_close:
                self.aapl_red_streak += 1
            else:
                self.aapl_red_streak = 0

            self.previous_aapl_close = aapl_close

        if not all_bars_present:
            return

        spy_buy_reason = (
            current_spy_sma is not None
            and prior_spy_close is not None
            and prior_spy_sma is not None
            and prior_spy_close <= prior_spy_sma
            and spy_close > current_spy_sma
        )

        spy_sell_reason = (
            current_spy_sma is not None
            and prior_spy_close is not None
            and prior_spy_sma is not None
            and prior_spy_close >= prior_spy_sma
            and spy_close < current_spy_sma
        )

        aapl_buy_reason = self.aapl_red_streak >= 3
        aapl_sell_reason = (
            self.aapl_rsi.IsReady
            and float(self.aapl_rsi.Current.Value) > 60.0
        )

        if self.strategy_a_lot > 0 and spy_sell_reason:
            self.MarketOrder(self.spy, -self.strategy_a_lot)
            self.strategy_a_lot = 0

        if self.strategy_b_lot > 0 and aapl_sell_reason:
            self.MarketOrder(self.aapl, -self.strategy_b_lot)
            self.strategy_b_lot = 0

        if self.strategy_a_lot == 0 and spy_buy_reason and spy_close > 0:
            target_value = 0.40 * float(self.Portfolio.TotalPortfolioValue)
            quantity = int(math.floor(target_value / spy_close))

            if quantity > 0:
                self.MarketOrder(self.spy, quantity)
                self.strategy_a_lot = quantity

        if self.strategy_b_lot == 0 and aapl_buy_reason:
            aapl_close = float(bars[self.aapl].Close)

            if aapl_close > 0 and float(self.Portfolio.Cash) >= 20000.0:
                quantity = int(math.floor(20000.0 / aapl_close))

                if quantity > 0:
                    self.MarketOrder(self.aapl, quantity)
                    self.strategy_b_lot = quantity
