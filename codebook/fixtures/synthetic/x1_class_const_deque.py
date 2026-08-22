from AlgorithmImports import *
from collections import deque
class A(QCAlgorithm):
    SMA_PERIOD = 20
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.spy_closes = deque(maxlen=self.SMA_PERIOD)
    def OnData(self, data):
        self.spy_closes.append(data[self.spy].Close)
        if len(self.spy_closes) == self.SMA_PERIOD:
            spy_sma = sum(self.spy_closes) / self.SMA_PERIOD
