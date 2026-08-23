from AlgorithmImportLib import *

class QuantConnectLeanAlgorithm(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2006, 1, 3)
        self.SetEndDate(2015, 12, 31)
        self.SetCash(1000000)
        
        tickers = ["SPY", "AAPL", "IBM", "BAC", "AIG"]
        self.symbols = {}
        for ticker in tickers:
            self.symbols[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol
        
        self.spy_closes = []
        self.aapl_closes = []
        self.sma_period = 20
        self.rsi_period = 14
    
    def OnData(self, data):
        for symbol in self.symbols.values():
            if not data.ContainsKey(symbol):
                return
        
        spy_close = data[self.symbols["SPY"]].Close
        aapl_close = data[self.symbols["AAPL"]].Close
        
        self.spy_closes.append(spy_close)
        self.aapl_closes.append(aapl_close)
        
        if len(self.spy_closes) > self.sma_period + 1:
            self.spy_closes.pop(0)
        if len(self.aapl_closes) > self.rsi_period + 1:
            self.aapl_closes.pop(0)
        
        if len(self.spy_closes) < self.sma_period + 1 or len(self.aapl_closes) < self.rsi_period + 1:
            return
        
        self.evaluate_sells(spy_close, aapl_close)
        self.evaluate_buys(spy_close, aapl_close)
    
    def evaluate_sells(self, spy_close, aapl_close):
        spy_qty = self.Portfolio[self.symbols["SPY"]].Quantity
        if spy_qty > 0:
            prev_close = self.spy_closes[-2]
            prev_sma = sum(self.spy_closes[:-1]) / self.sma_period
            curr_sma = sum(self.spy_closes[1:]) / self.sma_period
            
            if prev_close > prev_sma and spy_close <= curr_sma:
                self.Liquidate(self.symbols["SPY"])
        
        aapl_qty = self.Portfolio[self.symbols["AAPL"]].Quantity
        if aapl_qty > 0:
            rsi = self.calculate_rsi(self.aapl_closes)
            if rsi is not None and rsi > 60:
                self.Liquidate(self.symbols["AAPL"])
    
    def evaluate_buys(self, spy_close, aapl_close):
        spy_qty = self.Portfolio[self.symbols["SPY"]].Quantity
        if spy_qty == 0:
            prev_close = self.spy_closes[-2]
            prev_sma = sum(self.spy_closes[:-1]) / self.sma_period
            curr_sma = sum(self.spy_closes[1:]) / self.sma_period
            
            if prev_close <= prev_sma and spy_close > curr_sma:
                portfolio_value = self.Portfolio.TotalPortfolioValue
                invest_amount = portfolio_value * 0.4
                qty = int(invest_amount / spy_close)
                if qty > 0:
                    self.Buy(self.symbols["SPY"], qty)
        
        aapl_qty = self.Portfolio[self.symbols["AAPL"]].Quantity
        if aapl_qty == 0:
            red_count = 0
            for i in range(len(self.aapl_closes) - 1, len(self.aapl_closes) - 4, -1):
                if i > 0 and self.aapl_closes[i] < self.aapl_closes[i-1]:
                    red_count += 1
                else:
                    break
            
            if red_count >= 3:
                if self.Portfolio.Cash >= 20000:
                    qty = int(20000 / aapl_close)
                    if qty > 0:
                        self.Buy(self.symbols["AAPL"], qty)
    
    def calculate_rsi(self, closes):
        if len(closes) < self.rsi_period + 1:
            return None
        
        relevant_closes = closes[-(self.rsi_period + 1):]
        
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(relevant_closes)):
            change = relevant_closes[i] - relevant_closes[i-1]
            if change > 0:
                gains += change
            else:
                losses -= change
        
        avg_gain = gains / self.rsi_period
        avg_loss = losses / self.rsi_period
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi
