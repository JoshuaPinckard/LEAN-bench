from AlgorithmImports import *
from decimal import Decimal


class ExactStrategySystemAlgorithm(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2006, 1, 3)
        self.SetEndDate(2015, 12, 31)
        self.SetCash(1000000)

        self.tickers = ["SPY", "AAPL", "IBM", "BAC", "AIG"]
        self.symbol_by_ticker = {}

        for ticker in self.tickers:
            security = self.AddEquity(ticker, Resolution.Daily)
            security.SetDataNormalizationMode(DataNormalizationMode.Adjusted)
            self.symbol_by_ticker[ticker] = security.Symbol

        self.symbols = [self.symbol_by_ticker[ticker] for ticker in self.tickers]

        self.spy = self.symbol_by_ticker["SPY"]
        self.aapl = self.symbol_by_ticker["AAPL"]

        self.spy_sma = SimpleMovingAverage(100)
        self.aapl_rsi = RelativeStrengthIndex(14, MovingAverageType.Wilders)

        self.previous_close = {symbol: None for symbol in self.symbols}
        self.aapl_red_streak = 0

        self.strategy_a_quantity = 0
        self.strategy_b_quantity = 0

        self.SetWarmUp(101, Resolution.Daily)

    def OnData(self, data):
        bars = {}
        all_subscribed_bars_present = True

        for symbol in self.symbols:
            if data.Bars.ContainsKey(symbol) and data.Bars[symbol] is not None:
                bars[symbol] = data.Bars[symbol]
            else:
                all_subscribed_bars_present = False

        spy_previous_close = self.previous_close[self.spy]
        spy_previous_sma_ready = self.spy_sma.IsReady
        spy_previous_sma = self.spy_sma.Current.Value if spy_previous_sma_ready else None

        if self.spy in bars:
            self.spy_sma.Update(bars[self.spy].EndTime, bars[self.spy].Close)

        if self.aapl in bars:
            aapl_bar = bars[self.aapl]
            aapl_previous_close = self.previous_close[self.aapl]

            if aapl_previous_close is not None:
                if aapl_bar.Close < aapl_previous_close:
                    self.aapl_red_streak += 1
                else:
                    self.aapl_red_streak = 0

            self.aapl_rsi.Update(aapl_bar.EndTime, aapl_bar.Close)

        for symbol, bar in bars.items():
            self.previous_close[symbol] = bar.Close

        if self.IsWarmingUp:
            return

        self.SyncPrivateLotsWithPortfolio()

        if not all_subscribed_bars_present:
            return

        spy_close = bars[self.spy].Close
        spy_current_sma_ready = self.spy_sma.IsReady
        spy_current_sma = self.spy_sma.Current.Value if spy_current_sma_ready else None

        aapl_close = bars[self.aapl].Close
        aapl_rsi_ready = self.aapl_rsi.IsReady
        aapl_rsi_value = self.aapl_rsi.Current.Value if aapl_rsi_ready else None

        strategy_a_indicators_ready = (
            spy_previous_close is not None
            and spy_previous_sma_ready
            and spy_current_sma_ready
        )

        strategy_b_indicators_ready = (
            self.previous_close[self.aapl] is not None
            and aapl_rsi_ready
        )

        # Sells before buys.

        # Slot 1 - Strategy A sell
        if self.strategy_a_quantity > 0 and strategy_a_indicators_ready:
            spy_crosses_below_sma = (
                spy_previous_close >= spy_previous_sma
                and spy_close < spy_current_sma
            )

            if spy_crosses_below_sma:
                self.MarketOrder(self.spy, -self.strategy_a_quantity, False, "Strategy A Sell")
                self.strategy_a_quantity = 0

        # Slot 2 - Strategy B sell
        if self.strategy_b_quantity > 0 and strategy_b_indicators_ready:
            if aapl_rsi_value > Decimal("60"):
                self.MarketOrder(self.aapl, -self.strategy_b_quantity, False, "Strategy B Sell")
                self.strategy_b_quantity = 0

        # Slot 1 - Strategy A buy
        if self.strategy_a_quantity == 0 and strategy_a_indicators_ready:
            spy_crosses_above_sma = (
                spy_previous_close <= spy_previous_sma
                and spy_close > spy_current_sma
            )

            if spy_crosses_above_sma:
                target_value = self.Portfolio.TotalPortfolioValue * Decimal("0.40")
                quantity = int(target_value / spy_close)

                if quantity > 0:
                    self.MarketOrder(self.spy, quantity, False, "Strategy A Buy")
                    self.strategy_a_quantity = quantity

        # Slot 2 - Strategy B buy
        if self.strategy_b_quantity == 0 and strategy_b_indicators_ready:
            if self.aapl_red_streak >= 3:
                cash_to_invest = Decimal("20000")

                if self.Portfolio.Cash >= cash_to_invest:
                    quantity = int(cash_to_invest / aapl_close)

                    if quantity > 0:
                        self.MarketOrder(self.aapl, quantity, False, "Strategy B Buy")
                        self.strategy_b_quantity = quantity

    def SyncPrivateLotsWithPortfolio(self):
        if self.strategy_a_quantity > 0:
            self.strategy_a_quantity = max(0, int(self.Portfolio[self.spy].Quantity))

        if self.strategy_b_quantity > 0:
            self.strategy_b_quantity = max(0, int(self.Portfolio[self.aapl].Quantity))
