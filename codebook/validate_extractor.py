"""Extractor validation (CODEBOOK-v2 SSF) — committed evidence, not a claim.
Two fixture sets:
  1. REAL: the 4 pinned-T1 model programs (copied into fixtures/real/) with
     TAPE-IMPLIED ground truth for the DOFs the council established by
     matching their on-disk tapes to the bank (fable-1/2/3 R1): sonnet_s0
     == strict donor; gpt55_s0 == ready_check donor; sonnet_s1 = per-rule
     readiness (B trades from ~bar 15); gpt55_s1 = zero-order run.
  2. SYNTHETIC OFF-PIN: hand-written programs exercising NON-pinned values
     and idioms the v1 extractor got wrong (SetHoldings 0.25, named
     constants, Decimal("0.40"), `> 2` streaks, Portfolio.Invested gating,
     RSI cross exit, today's-MA cross timing, EMA-of-gains RSI, 20_000).
Prints per-rule accuracy and exits non-zero below the registered floor.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dof_extract as X  # noqa: E402

REAL_DIR = HERE / "fixtures" / "real"
SYN_DIR = HERE / "fixtures" / "synthetic"

# tape-implied truth (only the dimensions the tape evidence pins)
REAL_TRUTH = {
    "T1v0_gpt55_s0.py": {"dof_warmup": "ready_check", "dof_rsi_smoothing": "wilder", "dof_input_field": "adjusted",
                         "dof_a_exec": "calc_shares", "num": {"BL-01b": 100, "BL-03": 40, "BL-05": 3, "BL-08": 60, "BL-07": 14, "PX-01": 20000}},
    "T1v0_gpt55_s1.py": {"dof_rsi_smoothing": "wilder", "dof_input_field": "adjusted",
                         "num": {"BL-01b": 100, "BL-03": 40, "BL-05": 3, "BL-08": 60, "BL-07": 14, "PX-01": 20000}},
    "T1v0_sonnet_s0.py": {"dof_warmup": "strict", "dof_rsi_smoothing": "wilder", "dof_input_field": "adjusted",
                          "dof_a_exec": "calc_shares", "num": {"BL-01b": 100, "BL-03": 40, "BL-05": 3, "BL-08": 60, "BL-07": 14, "PX-01": 20000}},
    "T1v0_sonnet_s1.py": {"dof_warmup": "ready_per_rule", "dof_rsi_smoothing": "wilder", "dof_input_field": "adjusted",
                          "num": {"BL-01b": 100, "BL-03": 40, "BL-05": 3, "BL-08": 60, "BL-07": 14, "PX-01": 20000}},
}

SYNTHETIC = {
    # ---- INJECTION REGRESSIONS (red team, 2026-08-17) -------------------

    # 1. An escaped quote desynchronized the hand-rolled `#` stripper, so the
    "inject_escaped_quote.py": ("""
from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol
        self.ma = self.EMA("SPY", 55)
        self.QUOTE = "\""  # spec: SMA(self.spy, 100); SetHoldings(self.spy, 0.40); RSI(self.aapl, 14); rsi > 60; streak >= 3; budget = 20000
    def OnData(self, data):
        self.MarketOrder(self.spy, 1)
""", {"num": {"BL-01b": None, "BL-03": None, "BL-05": None, "BL-07": None, "BL-08": None, "PX-01": None}}),

    # 2. Implicit concatenation: two tokens each entirely numeric passed the
    #    per-token carve-out, and the regex read only the first — 0.45 coded
    #    as the pinned pct40. The rounding defect via a different door.
    "inject_concat.py": ("""
from AlgorithmImports import *
from decimal import Decimal
class A(QCAlgorithm):
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
    def OnData(self, data):
        self.SetHoldings(self.spy, Decimal("0.4" "5"))
""", {"num": {"BL-03": None}}),

    # 3. The triple-quote pre-regex ran on RAW text, so two ordinary literals
    "inject_splice.py": ("""
from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.Q1 = "'''"
    def OnData(self, data):
        self.SetHoldings(self.spy, 0.25)
        self._legacy_size = 0.40
        self.Q2 = "'''"
""", {"num": {"BL-03": 25}}),

    # 4. An unterminated string does NOT raise on CPython 3.11 — tokenize
    "inject_unterminated.py": ("""
from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        x = "note: SetHoldings(self.spy, 0.40) and SMA(self.spy, 100)
    def OnData(self, data):
        self.MarketOrder(self.spy, 1)
""", {"num": {"BL-03": None, "BL-01b": None}}),


    # ANTI-INJECTION (council R2, terra-1 — the filing recorded as "returned
    "string_injection.py": ("""
from AlgorithmImports import *
from decimal import Decimal
class A(QCAlgorithm):
    def Initialize(self):
        self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.Debug("legacy note: SetHoldings(self.spy, 0.40) was the old sizing")
        self.note = "we tried SMA(100) first, then RSI('AAPL', 14)"
        self.plan = "budget = 20000 in the old draft"
        self.ma = self.EMA("SPY", 55)
    def OnData(self, data):
        self.MarketOrder(self.spy, 1)
""", {"num": {"BL-03": None, "BL-01b": None, "PX-01": None, "BL-07": None}}),

    "sh_025.py": ("""
from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.sma = self.SMA(self.spy, 100, Resolution.Daily)
        self.SetWarmUp(100)
    def OnData(self, data):
        if self.IsWarmingUp: return
        if not self.Portfolio[self.spy].Invested and data[self.spy].Close > self.sma.Current.Value:
            self.SetHoldings(self.spy, 0.25)
        elif self.Portfolio[self.spy].Invested and data[self.spy].Close < self.sma.Current.Value:
            self.Liquidate(self.spy)
""", {"dof_a_exec": "set_holdings", "dof_warmup": "strict", "dof_same_bar_reentry": "wait_bar", "dof_cross_timing": "today_ma",
      "num": {"BL-03": 25, "BL-01b": 100}}),
    "named_const.py": ("""
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
""", {"dof_a_exec": "calc_shares", "dof_warmup": "ready_check", "dof_same_bar_reentry": "allowed",
      "num": {"BL-08": 70, "BL-05": 4, "BL-03": 50, "BL-07": 9, "BL-01b": 50}}),
    "decimal_gt2.py": ("""
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
""", {"dof_rsi_smoothing": "simple", "dof_same_bar_reentry": "wait_bar", "dof_cross_timing": "both_days",
      # BL-05 CORRECTED 2026-08-17. The fixture reads `if self.streak > 2`,
      "num": {"BL-05": 3, "BL-08": 60, "BL-03": 40, "PX-01": 20000, "BL-07": 14}, "cmp": {"BL-05": ">=", "BL-08": ">="}}),
    "rsi_cross_raw.py": ("""
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
""", {"dof_input_field": "raw", "dof_rsi_exit": "cross", "dof_rsi_smoothing": "wilder", "num": {"BL-08": 60, "BL-07": 14}}),
    "underscore_cash.py": ("""
from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        self.SetCash(1000000)
        self.aapl = self.AddEquity("AAPL", Resolution.Daily).Symbol
    def OnData(self, data):
        if self.Portfolio.Cash >= 20_000:
            shares = int(20_000 / data[self.aapl].Close)
            self.MarketOrder(self.aapl, shares)
""", {"num": {"PX-01": 20000}}),
    "comment_trap.py": ("""
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
""", {"dof_rsi_smoothing": "wilder", "dof_input_field": "adjusted", "num": {"BL-07": 21, "BL-08": 80}}),

    # ---- X1: CLASS-CONSTANT-VIA-SELF (real pattern, 2026-08-18 codex probe:
    #      5/10 committing BL-01b programs wrote `SMA_PERIOD = 20` at class
    #      level and read it as `self.SMA_PERIOD` — a human reads p20
    #      instantly; the table keyed only the bare name) -------------------

    # constructor arg through the class constant
    "x1_class_const_self.py": ("""
from AlgorithmImports import *
class A(QCAlgorithm):
    SMA_PERIOD = 20
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.spy_sma = SimpleMovingAverage(self.SMA_PERIOD)
    def OnData(self, data):
        self.MarketOrder(self.spy, 1)
""", {"num": {"BL-01b": 20}}),

    # manual rolling window: the period lives in deque(maxlen=self.CONST)
    "x1_class_const_deque.py": ("""
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
""", {"num": {"BL-01b": 20}}),

    # GUARD: a non-numeric instance assignment shadows the class constant at
    # runtime, so the alias must NOT fire — stays unresolved, never guessed
    "x1_const_shadowed_guard.py": ("""
from AlgorithmImports import *
class A(QCAlgorithm):
    SMA_PERIOD = 20
    def Initialize(self):
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.SMA_PERIOD = self.GetParameter("sma_period")
        self.spy_sma = SimpleMovingAverage(self.SMA_PERIOD)
    def OnData(self, data):
        self.MarketOrder(self.spy, 1)
""", {"num": {"BL-01b": None}}),
}


def run():
    REAL_DIR.mkdir(parents=True, exist_ok=True); SYN_DIR.mkdir(parents=True, exist_ok=True)
    # Fixtures are COMMITTED artifacts: write only if absent, else verify the
    # on-disk bytes equal the registered source. A validator that rewrites its
    # own fixtures on every run validates nothing (opus-1 R2 #7).
    for name, (code, _) in SYNTHETIC.items():
        f = SYN_DIR / name
        want = code.strip() + "\n"
        if not f.exists():
            f.write_text(want, encoding="utf-8")
        elif f.read_text(encoding="utf-8") != want:
            print(f"FIXTURE DRIFT: {f} differs from the registered source")
            return 2
    ok = tot = 0
    misses = []
    def check(label, got, exp):
        nonlocal ok, tot
        for k, v in exp.items():
            if k in ("num", "cmp"):
                continue
            tot += 1
            if got.get(k) == v: ok += 1
            else: misses.append((label, k, v, got.get(k)))
    def check_num(label, text, exp_num, exp_cmp=None):
        nonlocal ok, tot
        for b, v in exp_num.items():
            tot += 1
            r = X.numeric(b, text)
            if r["value"] == v: ok += 1
            else: misses.append((label, "num:" + b, v, r))
            if exp_cmp and b in exp_cmp:
                tot += 1
                if r.get("comparator") == exp_cmp[b]: ok += 1
                else: misses.append((label, "cmp:" + b, exp_cmp[b], r.get("comparator")))
    for fn, exp in REAL_TRUTH.items():
        p = REAL_DIR / fn
        if not p.exists():
            print("MISSING real fixture", fn); continue
        text = p.read_text(encoding="utf-8", errors="replace")
        got = X.extract(text)
        check("real/" + fn, got, exp)
        check_num("real/" + fn, text, exp["num"])
    for fn, (code, exp) in SYNTHETIC.items():
        text = (SYN_DIR / fn).read_text(encoding="utf-8")   # the COMMITTED file
        got = X.extract(text)
        check("syn/" + fn, got, exp)
        check_num("syn/" + fn, text, exp.get("num", {}), exp.get("cmp"))
    print(f"EXTRACTOR VALIDATION: {ok}/{tot} correct")
    for m in misses:
        print("  MISS", m)
    rep = {"ok": ok, "total": tot, "misses": [list(map(str, m)) for m in misses]}
    (HERE / "VALIDATION-REPORT.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    floor = 0.90
    return 0 if tot and ok / tot >= floor else 1


if __name__ == "__main__":
    sys.exit(run())
