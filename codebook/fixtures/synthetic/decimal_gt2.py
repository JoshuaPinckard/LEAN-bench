from AlgorithmImports import *
from decimal import Decimal
class A(QCAlgorithm):
    def Initialize(self):
        self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.rsi = RelativeStrengthIndex(14, MovingAverageType.Simple)
        self.streak = 0
        self.prev_sma = None
    def OnData(self, data):
        if self.streak > 2 and not self.Portfolio[self.aapl].Invested:
            cash = Decimal("20000")
            if self.Portfolio.Cash >= cash:
                self.MarketOrder(self.aapl, int(cash / data[self.aapl].Close))
        target = self.Portfolio.TotalPortfolioValue * Decimal("0.40")
        if self.rsi.Current.Value >= Decimal("60") and self.Portfolio[self.aapl].Invested:
            self.Liquidate(self.aapl)
