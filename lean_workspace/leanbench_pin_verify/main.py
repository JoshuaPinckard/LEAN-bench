from AlgorithmImports import *


class PinVerifyAlgorithm(QCAlgorithm):
    """Minimal algorithm used to verify that the pinned LEAN engine image
    digest is what actually executes a backtest. Two trading days, one
    equity, no logic. The check is on which image runs, not what runs."""

    def Initialize(self):
        self.SetStartDate(2020, 1, 2)
        self.SetEndDate(2020, 1, 3)
        self.SetCash(100000)
        self.AddEquity("SPY", Resolution.Daily)

    def OnData(self, data):
        pass
