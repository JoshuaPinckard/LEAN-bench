from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        s = self.AddEquity("AAPL", Resolution.Daily)
        s.SetDataNormalizationMode(DataNormalizationMode.Raw)
        self.aapl = s.Symbol
        self.rsi = self.RSI(self.aapl, 14)
        self.prev_rsi = None
        self.holding = False
    def OnData(self, data):
        if not self.rsi.IsReady: return
        cur = self.rsi.Current.Value
        if self.holding and self.prev_rsi is not None and self.prev_rsi <= 60 and cur > 60:
            self.Liquidate(self.aapl); self.holding = False
        self.prev_rsi = cur
