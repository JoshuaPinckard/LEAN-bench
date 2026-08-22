from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        self.SetCash(1000000)
        self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol
    def OnData(self, data):
        if self.Portfolio.Cash >= 20_000:
            shares = int(20_000 / data[self.aapl].Close)
            self.MarketOrder(self.aapl, shares)
