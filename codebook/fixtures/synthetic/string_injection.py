from AlgorithmImports import *
from decimal import Decimal
class A(QCAlgorithm):
    def Initialize(self):
        self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.Debug("legacy note: SetHoldings(self.spy, 0.40) was the old sizing")
        self.note = "we tried SMA(100) first, then RSI('AAPL', 14)"
        self.plan = "budget = 20000 in the old draft"
        self.ma = self.EMA("SPY", 55)
    def OnData(self, data):
        self.MarketOrder(self.spy, 1)
