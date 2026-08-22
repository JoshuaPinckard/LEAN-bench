from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        x = "note: SetHoldings(self.spy, 0.40) and SMA(self.spy, 100)
    def OnData(self, data):
        self.MarketOrder(self.spy, 1)
