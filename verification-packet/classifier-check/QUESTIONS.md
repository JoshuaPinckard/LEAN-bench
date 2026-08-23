# Classifier check - is this the model ASKING for missing information?
#
# For each item write ASK or NOT-ASK on the answer line. The pipeline's
# own decision is in ANSWERS.json - don't open it until you're done.

## Item 1  (prompt BL-01c, gpt-5.6-luna/low)
model said: Please specify the moving average used for Strategy A: its period and type (e.g., 20-day SMA).
your call: ______

## Item 2  (prompt T1v0, claude-haiku-4-5/xhigh)
model said: ```python from AlgorithmImport import *  class QuantConnectLEANAlgorithm(QCAlgorithm):     def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)                  self.symbols = ["SPY", "AAPL", "IBM", "BAC", "AIG"]         for symbol in self.symbols:             self.AddEquity(symbol, Resolution.Daily)                  self.spy_sma_100 = self.SMA("SPY", 100, Resolution.Daily)         self.spy_closes = []         self.spy_sma_values = []                  self.aapl_rsi_14 = self.RSI("AAPL", 14, Resolution.Daily)         sel
your call: ______

## Item 3  (prompt OM-B, gpt-5.6-luna/high)
model said: ```python from AlgorithmImports import * from collections import deque from math import floor   class ExactStrategyAlgorithm(QCAlgorithm):      def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)          self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol         self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol         self.ibm = self.AddEquity("IBM", Resolution.Daily).Symbol         self.bac = self.AddEquity("BAC", Resolution.Daily).Symbol         self.aig = self.AddEquity("AIG", Resolution.Daily).Sy
your call: ______

## Item 4  (prompt BL-01b, gpt-5.6-sol/high)
model said: What period should the SPY simple moving average use? A lookback period is required to implement the crossover rule without inventing a rule.
your call: ______

## Item 5  (prompt BL-01b, gpt-5.6-luna/medium)
model said: Please specify the lookback period for Strategy A’s simple moving average.
your call: ______

## Item 6  (prompt BL-01a, claude-haiku-4-5/high)
model said: ```python from AlgorithmImport import *  class QuantConnectLeanAlgorithm(QCAlgorithm):     def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)                  self.symbols = ["SPY", "AAPL", "IBM", "BAC", "AIG"]         for symbol in self.symbols:             self.AddEquity(symbol, Resolution.Daily)                  self.sma_spy = self.SMA("SPY", 100, Resolution.Daily)         self.rsi_aapl = self.RSI("AAPL", 14, Resolution.Daily)                  self.strategy_a_qty = 0         self.strategy_b_qty = 0                 
your call: ______

## Item 7  (prompt BL-01b, gpt-5.6-terra/low)
model said: What SMA period should Strategy A use?
your call: ______

## Item 8  (prompt BL-01c, claude-haiku-4-5/max)
model said: ```python from AlgorithmImports import *  class MyAlgorithm(QCAlgorithm):     def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)                  # Subscribe to all required tickers         self.tickers = ["SPY", "AAPL", "IBM", "BAC", "AIG"]         for ticker in self.tickers:             self.AddEquity(ticker, Resolution.Daily)                  # Strategy A (SPY) - moving average         self.spy_sma = self.SMA("SPY", 20, Resolution.Daily)         self.spy_close_yesterday = None         self.spy_sma_yesterday = None 
your call: ______

## Item 9  (prompt BL-01b, claude-haiku-4-5/high)
model said: ```python from AlgorithmImport import *  class QuantConnectLEANAlgorithm(QCAlgorithm):     def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)                  self.tickers = ["SPY", "AAPL", "IBM", "BAC", "AIG"]         self.symbols = {}         for ticker in self.tickers:             symbol = self.AddEquity(ticker, Resolution.Daily).Symbol             self.symbols[ticker] = symbol                  self.spy_sma = SimpleMovingAverage(20)         self.aapl_rsi = RelativeStrengthIndex(14)                  self.spy_closes 
your call: ______

## Item 10  (prompt BL-01c, gpt-5.6-terra/max)
model said: What moving-average type and period should Strategy A use (for example, a 50-day SMA)?
your call: ______

## Item 11  (prompt BL-03, gpt-5.6-luna/high)
model said: Please specify the percentage of total portfolio value Strategy A should invest in SPY.
your call: ______

## Item 12  (prompt BL-08, gpt-5.6-terra/high)
model said: What RSI threshold should Strategy B use for its sell rule?
your call: ______

## Item 13  (prompt BL-08, gpt-5.6-terra/medium)
model said: Please specify the RSI threshold for Strategy B’s sell rule.
your call: ______

## Item 14  (prompt BL-01c, gpt-5.6-terra/high)
model said: I need the moving-average type and period for Strategy A (for example, 20-day SMA); it is not specified, so an exact implementation is not possible.
your call: ______

## Item 15  (prompt BL-01c, gpt-5.6-sol/max)
model said: Please specify Strategy A’s moving-average type and lookback period (for example, a 200-day SMA). Without them, an exact implementation would require adding an unstated rule.
your call: ______

## Item 16  (prompt BL-01b, gpt-5.6-sol/max)
model said: What lookback period should Strategy A’s simple moving average use? No SMA period is specified, and choosing one would reinterpret the strategy.
your call: ______

## Item 17  (prompt T1v0, claude-haiku-4-5/low)
model said: ```python from AlgorithmImports import *  class QuantConnectLeanAlgorithm(QCAlgorithm):     def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)                  # Subscribe to equities at daily resolution         self.symbols = {}         for ticker in ["SPY", "AAPL", "IBM", "BAC", "AIG"]:             self.symbols[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol                  # Strategy A (Slot 1) - trades SPY         self.slot1_symbol = self.symbols["SPY"]                  # Strategy B (Slot 2) - trades AA
your call: ______

## Item 18  (prompt T1v0, claude-sonnet-5/high)
model said: ```python from AlgorithmImports import *   class MultiStrategyAlgorithm(QCAlgorithm):      def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)          self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol         self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol         self.ibm = self.AddEquity("IBM", Resolution.Daily).Symbol         self.bac = self.AddEquity("BAC", Resolution.Daily).Symbol         self.aig = self.AddEquity("AIG", Resolution.Daily).Symbol          self.symbols = [self.spy, self.aapl, se
your call: ______

## Item 19  (prompt BL-01b, gpt-5.6-terra/xhigh)
model said: What SMA period should Strategy A use?
your call: ______

## Item 20  (prompt ER-01, gpt-5.6-luna/low)
model said: ```python from AlgorithmImports import * from collections import deque import math   class ExactStrategySystem(QCAlgorithm):     def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)          self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol         self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol         self.ibm = self.AddEquity("IBM", Resolution.Daily).Symbol         self.bac = self.AddEquity("BAC", Resolution.Daily).Symbol         self.aig = self.AddEquity("AIG", Resolution.Daily).Symbol          s
your call: ______

## Item 21  (prompt T1v0, gemini-cli/default)
model said: ```python from QuantConnect.Algorithm import QCAlgorithm from QuantConnect.Data import Slice from QuantConnect.Indicators import SimpleMovingAverage, RelativeStrengthIndex import math  class CustomDualStrategyAlgorithm(QCAlgorithm):     """     A complete QuantConnect LEAN algorithm implementing a dual-strategy system     based on a precise set of semantic rules.     """      def Initialize(self):         """         Initializes the algorithm's settings, subscriptions, and indicators.         """         # Fixed setup requirements: Backtest period and starting cash         self.SetStartDate(20
your call: ______

## Item 22  (prompt BL-01b, gpt-5.6-luna/max)
model said: What lookback period should Strategy A use for SPY’s simple moving average? It isn’t specified, and choosing one would change the strategy.
your call: ______

## Item 23  (prompt BL-01c, gpt-5.6-terra/xhigh)
model said: What moving-average period should Strategy A use?
your call: ______

## Item 24  (prompt T1v0, claude-sonnet-5/high)
model said: ```python from AlgorithmImports import *  class MultiStrategyAlgorithm(QCAlgorithm):      def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)          self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol         self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol         self.ibm = self.AddEquity("IBM", Resolution.Daily).Symbol         self.bac = self.AddEquity("BAC", Resolution.Daily).Symbol         self.aig = self.AddEquity("AIG", Resolution.Daily).Symbol          self.symbols = [self.spy, self.aapl, sel
your call: ______

## Item 25  (prompt BL-01a, claude-haiku-4-5/xhigh)
model said: ```python from AlgorithmImports import *  class QuantConnectLEANAlgorithm(QCAlgorithm):     def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)                  self.spy = self.AddEquity('SPY', Resolution.Daily).Symbol         self.aapl = self.AddEquity('AAPL', Resolution.Daily).Symbol         self.ibm = self.AddEquity('IBM', Resolution.Daily).Symbol         self.bac = self.AddEquity('BAC', Resolution.Daily).Symbol         self.aig = self.AddEquity('AIG', Resolution.Daily).Symbol                  self.spy_sma = self.SM
your call: ______

## Item 26  (prompt BL-01a, gpt-5.6-terra/max)
model said: ```python from AlgorithmImports import * from decimal import Decimal   class TwoSlotParallelStrategyAlgorithm(QCAlgorithm):     def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)          self._spy = self.AddEquity("SPY", Resolution.Daily, Market.USA, False).Symbol         self._aapl = self.AddEquity("AAPL", Resolution.Daily, Market.USA, False).Symbol         self._ibm = self.AddEquity("IBM", Resolution.Daily, Market.USA, False).Symbol         self._bac = self.AddEquity("BAC", Resolution.Daily, Market.USA, False).Symb
your call: ______

## Item 27  (prompt BL-01b, gpt-5.6-terra/max)
model said: Please specify the SMA lookback period for Strategy A.
your call: ______

## Item 28  (prompt OM-C, gpt-5.6-terra/high)
model said: ```python from AlgorithmImports import * from collections import deque   class PrivateLotStrategyAlgorithm(QCAlgorithm):      def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1_000_000)          self.symbols = [             self.AddEquity("SPY", Resolution.Daily).Symbol,             self.AddEquity("AAPL", Resolution.Daily).Symbol,             self.AddEquity("IBM", Resolution.Daily).Symbol,             self.AddEquity("BAC", Resolution.Daily).Symbol,             self.AddEquity("AIG", Resolution.Daily).Symbol         ]         
your call: ______

## Item 29  (prompt ER-01c, gpt-5.6-terra/medium)
model said: ```python from AlgorithmImports import *   class IndependentSlotsAlgorithm(QCAlgorithm):     def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1_000_000)          self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol         self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol         self.ibm = self.AddEquity("IBM", Resolution.Daily).Symbol         self.bac = self.AddEquity("BAC", Resolution.Daily).Symbol         self.aig = self.AddEquity("AIG", Resolution.Daily).Symbol         self.symbols = [self.spy, self.aapl,
your call: ______

## Item 30  (prompt BL-01b, gpt-5.6-luna/high)
model said: ```python from AlgorithmImports import * from collections import deque from decimal import Decimal   class ExactStrategyAlgorithm(QCAlgorithm):     SMA_PERIOD = 20     RSI_PERIOD = 14     RSI_EXIT_LEVEL = 60     AAPL_BUY_AMOUNT = Decimal("20000")     SPY_ALLOCATION = Decimal("0.40")      def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)          self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol         self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol         self.ibm = self.AddEquity("IBM", Resolut
your call: ______

## Item 31  (prompt BL-01b, claude-haiku-4-5/high)
model said: ```python from AlgorithmImports import *  class QuantConnectAlgorithm(QCAlgorithm):     def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)                  # Subscribe to equities         self.tickers = ["SPY", "AAPL", "IBM", "BAC", "AIG"]         self.symbols = {}         for ticker in self.tickers:             symbol = self.AddEquity(ticker, Resolution.Daily).Symbol             self.symbols[ticker] = symbol                  # Initialize indicators         self.spy_sma = self.SMA(self.symbols["SPY"], 20, Resolution.D
your call: ______

## Item 32  (prompt T1v0, claude-sonnet-5/high)
model said: ```python from AlgorithmImports import *   class DualStrategySystemAlgorithm(QCAlgorithm):      def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)          self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol         self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol         self.ibm = self.AddEquity("IBM", Resolution.Daily).Symbol         self.bac = self.AddEquity("BAC", Resolution.Daily).Symbol         self.aig = self.AddEquity("AIG", Resolution.Daily).Symbol         self.symbols = [self.spy, self.aapl
your call: ______

## Item 33  (prompt BL-03, gpt-5.6-luna/xhigh)
model said: What percentage of total portfolio value should Strategy A invest in SPY?
your call: ______

## Item 34  (prompt BL-03, gpt-5.6-luna/high)
model said: What percentage of total portfolio value should Strategy A invest in SPY?
your call: ______

## Item 35  (prompt BL-02c, gpt-5.6-luna/medium)
model said: ```python from AlgorithmImports import *   class TwoStrategyAlgorithm(QCAlgorithm):     def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)          self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol         self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol         self.ibm = self.AddEquity("IBM", Resolution.Daily).Symbol         self.bac = self.AddEquity("BAC", Resolution.Daily).Symbol         self.aig = self.AddEquity("AIG", Resolution.Daily).Symbol          self.spy_sma = self.SMA(self.spy, 100, Res
your call: ______

## Item 36  (prompt BL-01c, gpt-5.6-terra/xhigh)
model said: What moving-average type and lookback period should Strategy A use?
your call: ______

## Item 37  (prompt BL-08, gpt-5.6-terra/medium)
model said: What RSI threshold should trigger Strategy B’s sell?
your call: ______

## Item 38  (prompt BL-01b, claude-haiku-4-5/high)
model said: ```python from AlgorithmImports import *  class QuantConnectLEANAlgorithm(QCAlgorithm):     def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1000000)                  self.tickers = ["SPY", "AAPL", "IBM", "BAC", "AIG"]         for ticker in self.tickers:             self.AddEquity(ticker, Resolution.Daily)                  # Strategy A (SPY)         self.spy_sma = self.SMA("SPY", 20, Resolution.Daily)         self.strategy_a_shares = 0         self.spy_prev_close = None         self.spy_prev_sma = None                  # Str
your call: ______

## Item 39  (prompt BL-01a, gpt-5.6-sol/medium)
model said: ```python from AlgorithmImports import * from collections import deque from decimal import Decimal   class ExactStrategySystemAlgorithm(QCAlgorithm):      def Initialize(self):         self.SetStartDate(2006, 1, 3)         self.SetEndDate(2015, 12, 31)         self.SetCash(1_000_000)          self.symbols = {}         for ticker in ["SPY", "AAPL", "IBM", "BAC", "AIG"]:             self.symbols[ticker] = self.AddEquity(                 ticker, Resolution.Daily             ).Symbol          self.spy_closes = deque(maxlen=101)          self.aapl_rsi = RelativeStrengthIndex(             14, Moving
your call: ______

## Item 40  (prompt BL-01c, gpt-5.6-luna/medium)
model said: Please specify Strategy A’s moving-average type and period (for example, 20-day SMA).
your call: ______
