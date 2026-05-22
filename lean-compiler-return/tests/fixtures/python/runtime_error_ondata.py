from AlgorithmImports import *


class BacktestAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2020, 1, 6)
        self.set_end_date(2020, 1, 10)
        self.set_cash(100000)
        self.add_equity("SPY", Resolution.DAILY)
        self._bars_seen = 0

    def on_data(self, slice):
        self._bars_seen += 1
        if self._bars_seen >= 2:
            _ = 1 / 0  # intentional runtime failure after a couple of bars
