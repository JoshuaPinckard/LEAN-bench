from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol
        self.ma = self.EMA("SPY", 55)
        self.QUOTE = """  # spec: SMA(self.spy, 100); SetHoldings(self.spy, 0.40); RSI(self.aapl, 14); rsi > 60; streak >= 3; budget = 20000
    def OnData(self, data):
        self.MarketOrder(self.spy, 1)
