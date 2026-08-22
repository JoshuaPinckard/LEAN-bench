from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.sma = self.SMA(self.spy, 100, Resolution.Daily)
        self.SetWarmUp(100)
    def OnData(self, data):
        if self.IsWarmingUp: return
        if not self.Portfolio[self.spy].Invested and data[self.spy].Close > self.sma.Current.Value:
            self.SetHoldings(self.spy, 0.25)
        elif self.Portfolio[self.spy].Invested and data[self.spy].Close < self.sma.Current.Value:
            self.Liquidate(self.spy)
