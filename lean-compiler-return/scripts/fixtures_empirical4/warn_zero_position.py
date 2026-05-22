"""EMPIRICAL #4 fixture: SetHoldings(symbol, 0) — i.e., the user thinks they're
placing a position but they're setting it to zero. Looking for: does LEAN
emit any warning that the order is a no-op?"""
from AlgorithmImports import *


class BacktestAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2020, 1, 6)
        self.set_end_date(2020, 1, 10)
        self.set_cash(100000)
        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self._ran = False

    def on_data(self, slice):
        if not self._ran and self.spy in slice.bars:
            self.set_holdings(self.spy, 0)
            self._ran = True
