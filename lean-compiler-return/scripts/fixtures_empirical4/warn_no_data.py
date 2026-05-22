"""EMPIRICAL #4 fixture: subscribe to a symbol with no data available for the
date range. NOT part of the core 12; only used to characterize warning
emissions."""
from AlgorithmImports import *


class BacktestAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2020, 1, 6)
        self.set_end_date(2020, 1, 10)
        self.set_cash(100000)
        # ZXYW is not a real ticker — LEAN should fail to resolve a
        # subscription for it. Looking for: warn/error/silent.
        self.add_equity("ZXYW", Resolution.DAILY)

    def on_data(self, slice):
        pass
