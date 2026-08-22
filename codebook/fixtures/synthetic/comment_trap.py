from AlgorithmImports import *
class A(QCAlgorithm):
    # uses RSI(14) and MovingAverageType.Simple in a comment only
    def Initialize(self):
        self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol
        self.rsi = self.RSI(self.aapl, 21, MovingAverageType.Wilders)  # 21 not 14
        '''docstring mentions SetWarmUp(500) and DataNormalizationMode.Raw'''
    def OnData(self, data):
        if not self.rsi.IsReady: return
        if self.rsi.Current.Value > 80: self.Liquidate(self.aapl)
