from AlgorithmImports import *


class BacktestAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2020, 1, 6)
        self.set_end_date(2020, 1, 10)
        self.set_cash(100000)
        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self._bought = False

    def on_data(self, slice):
        if not self._bought and self.spy in slice.bars:
            self.set_holdings(self.spy, 1.0)
            self._bought = True
