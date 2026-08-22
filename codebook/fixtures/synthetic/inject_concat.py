from AlgorithmImports import *
from decimal import Decimal
class A(QCAlgorithm):
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
    def OnData(self, data):
        self.SetHoldings(self.spy, Decimal("0.4" "5"))
