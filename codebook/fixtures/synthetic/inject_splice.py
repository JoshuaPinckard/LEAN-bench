from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.Q1 = "'''"
    def OnData(self, data):
        self.SetHoldings(self.spy, 0.25)
        self._legacy_size = 0.40
        self.Q2 = "'''"
