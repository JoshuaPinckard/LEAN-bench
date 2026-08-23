from AlgorithmImports import *


class ExactStrategySystem(QCAlgorithm):
    def Initialize(self):
        raise ValueError(
            "Strategy A's moving-average type and lookback period are unspecified, "
            "so the strategy cannot be implemented exactly without adding or "
            "reinterpreting a rule."
        )
