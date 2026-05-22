from AlgorithmImports import *


class BacktestAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2020, 1, 6)
        self.set_end_date(2020, 1, 10)
        self.set_cash(100000)
        self.add_equity("SPY", Resolution.DAILY)

    def on_data(self, slice):
        pass
