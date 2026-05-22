"""EMPIRICAL #4 fixture: indicator warmup window longer than backtest range.
Looking for: does LEAN warn that the indicator never warmed up?"""
from AlgorithmImports import *


class BacktestAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2020, 1, 6)
        self.set_end_date(2020, 1, 10)
        self.set_cash(100000)
        self.symbol = self.add_equity("SPY", Resolution.DAILY).symbol
        # 200-day SMA never warms up over a 4-day backtest.
        self.sma = self.sma(self.symbol, 200, Resolution.DAILY)

    def on_data(self, slice):
        # Reference the indicator so any unused-indicator paths fire.
        _ = self.sma.is_ready
