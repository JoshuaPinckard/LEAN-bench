from AlgorithmImports import *
class A(QCAlgorithm):
    SMA_PERIOD = 20
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.spy_sma = SimpleMovingAverage(self.SMA_PERIOD)
    def OnData(self, data):
        self.MarketOrder(self.spy, 1)
