from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        self.rsi_threshold = 70
        self.red_days_required = 4
        self.alloc = 0.5
        self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.rsi = self.RSI(self.aapl, 9, MovingAverageType.Wilders, Resolution.Daily)
        self.sma = self.SMA(self.spy, 50)
        self.red_streak = 0
        self.lot = 0
    def OnData(self, data):
        if not self.rsi.IsReady or not self.sma.IsReady: return
        if self.lot > 0 and self.rsi.Current.Value > self.rsi_threshold:
            self.MarketOrder(self.aapl, -self.lot); self.lot = 0
        if self.lot == 0 and self.red_streak >= self.red_days_required:
            q = int(self.Portfolio.TotalPortfolioValue * self.alloc / data[self.spy].Close)
            self.MarketOrder(self.aapl, q); self.lot = q
