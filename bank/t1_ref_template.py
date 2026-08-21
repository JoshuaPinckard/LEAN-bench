# T1 parameterized reference implementation v2 — PIN-v5 SS4.2 oracle bank.
# ONE audited code path; every oracle = this template + the PARAMS literal.
# v2 (2026-08-16, vetting-council round 1): fill-event lot sync for BOTH
# signs with pending-order tracking; LEAN-exact EMA seed (first value);
# readiness levels {strict, ready_check, ready_per_rule}; RSI exit
# {level, cross}; cross timing {both_days, today_ma}; level-relation cross
# resolutions; ER-01 lookback exact; missing-bar state update; OM-B
# eval-order resolution; split sync for raw private lots.
#
# PARAMS keys (defaults = the pinned donor at the reference DOF point):
#   a_ma_type: SMA|EMA|WMA            a_ma_period: int (100)
#   a_buy_dir/a_sell_dir: up|down|any|level_above|level_below
#   a_size_pct: float (40)            a_sell_frac: all|half_down_lastsell|half_down_hold|half_up
#   er01_sell: none|R1..R6            (buy = close x SMA200 up)
#   b_red_def: prev_close|open_close|prev_close_le   b_red_days: int (3)
#   b_cash_rule: skip|partial|nocheck b_cash_amt: float (20000)
#   b_rsi_period: int (14)            b_rsi_thresh: float (60)
#   missing_bar: skip_all|no_guard|try_except|per_ticker
#   lots: private|invested_gate|netting     eval_order: sells_first|buys_first
#   slot_mode: parallel|race|sequence
#   dof_rsi_smoothing: wilder|simple  dof_rsi_exit: level|cross
#   dof_warmup: strict|ready_check|ready_per_rule
#   dof_warmup_bars: int|null (strict: SetWarmUp length; null = minimal complete)
#   dof_a_exec: calc_shares|set_holdings|pct_cash
#   dof_same_bar_reentry: allowed|wait_bar
#   dof_input_field: adjusted|raw
#   dof_cross_timing: both_days|today_ma
#
# {{PARAMS}} is replaced by the bank runner with a JSON dict literal.

from AlgorithmImports import *
import json
import math

PARAMS = json.loads(r'''{{PARAMS}}''')


class T1Reference(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2006, 1, 3)
        self.SetEndDate(2015, 12, 31)
        self.SetCash(1000000)
        self.p = PARAMS
        # in-container witness of the executed source (bank_runner verifies it in log.txt)
        self.Log("RUN-NONCE " + str(self.p.get("_nonce", "none")))
        self.tickers = ["SPY", "AAPL", "IBM", "BAC", "AIG"]
        self.syms = {}
        for t in self.tickers:
            sec = self.AddEquity(t, Resolution.Daily)
            if self.p["dof_input_field"] == "raw":
                sec.SetDataNormalizationMode(DataNormalizationMode.Raw)
            self.syms[t] = sec.Symbol

        self.closes = {t: [] for t in self.tickers}
        self.opens = {t: [] for t in self.tickers}
        # EMA state per (period): [prev_value, cur_value] — LEAN semantics
        self.ema = {}

        # Lot state — from FILL EVENTS only (daily market orders fill at the
        # next open). shares = filled quantity owned; pending = submitted,
        # not yet filled quantity (signed); lot_open gates the contract's
        # "buy reason evaluated only while its lot is empty".
        self.a_shares = 0; self.a_pending = 0; self.a_lot_open = False
        self.b_shares = 0; self.b_pending = 0; self.b_lot_open = False
        self.a_last_action_bar = -10
        self.b_last_action_bar = -10
        self.bar_index = -1

        # RSI state
        self.rsi_avg_gain = None
        self.rsi_avg_loss = None
        self.rsi_seed = []
        self.rsi_value = None
        self.rsi_prev = None

        self.race_owner = None
        self.seq_eligible = 1
        self.seq_was_nonempty = False

        if self.p["dof_warmup"] == "strict":
            n = self.p.get("dof_warmup_bars") or self._lookback_all()
            self.SetWarmUp(int(n), Resolution.Daily)

    # ---------- exact readiness (contract: "fully formed") ----------

    def _lookback_a(self):
        # cross of X vs MA(n): MA yesterday AND today -> n+1 closes
        n = self.p["a_ma_period"] + 1
        if self.p["er01_sell"] != "none":
            n = max(n, 200 + 1, 50 + 1)
        return n

    def _lookback_b(self):
        # RSI(n) Wilder seed needs n changes -> n+1 closes; streak k -> k+1 closes
        return max(self.p["b_rsi_period"] + 1, self.p["b_red_days"] + 1)

    def _lookback_all(self):
        return max(self._lookback_a(), self._lookback_b())

    def _ready_a(self):
        return len(self.closes["SPY"]) >= self._lookback_a()

    def _ready_b(self):
        return len(self.closes["AAPL"]) >= self._lookback_b() and self.rsi_value is not None

    # ---------- indicators (manual, contract-exact) ----------

    def _ma_window(self, closes, n, kind):
        if len(closes) < n:
            return None
        w = closes[-n:]
        if kind == "SMA":
            return sum(w) / n
        if kind == "WMA":
            den = n * (n + 1) / 2.0
            return sum((i + 1) * c for i, c in enumerate(w)) / den
        raise ValueError(kind)

    def _update_ema(self, closes, n):
        # LEAN ExponentialMovingAverage: first sample seeds; then
        # ema = ema + k * (x - ema); IsReady after n samples
        k = 2.0 / (n + 1)
        st = self.ema.get(n)
        x = closes[-1]
        if st is None:
            self.ema[n] = [None, x, 1]
            return
        prev, cur, cnt = st
        self.ema[n] = [cur, cur + k * (x - cur), cnt + 1]

    def _ma_pair(self, closes, n, kind):
        """(MA yesterday, MA today) for the A-side pair test."""
        if kind == "EMA":
            st = self.ema.get(n)
            if st is None or st[2] < n + 1:
                return None, None
            return st[0], st[1]
        today = self._ma_window(closes, n, kind)
        yest = self._ma_window(closes[:-1], n, kind) if len(closes) >= n + 1 else None
        return yest, today

    def _crossed(self, x_y, x_t, y_y, y_t, direction):
        if None in (x_y, x_t, y_y, y_t):
            return False
        up = (x_y <= y_y) and (x_t > y_t)
        dn = (x_y >= y_y) and (x_t < y_t)
        if direction == "up":
            return up
        if direction == "down":
            return dn
        if direction == "any":
            return up or dn
        if direction == "level_above":
            return x_t > y_t
        if direction == "level_below":
            return x_t < y_t
        raise ValueError(direction)

    def _update_rsi(self, closes):
        n = self.p["b_rsi_period"]
        self.rsi_prev = self.rsi_value
        if len(closes) < 2:
            return
        ch = closes[-1] - closes[-2]
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if self.p["dof_rsi_smoothing"] == "simple":
            if len(closes) < n + 1:
                self.rsi_value = None
                return
            chs = [closes[i] - closes[i - 1] for i in range(len(closes) - n, len(closes))]
            ag = sum(max(c, 0.0) for c in chs) / n
            al = sum(max(-c, 0.0) for c in chs) / n
        else:
            if self.rsi_avg_gain is None:
                self.rsi_seed.append((g, l))
                if len(self.rsi_seed) < n:
                    self.rsi_value = None
                    return
                self.rsi_avg_gain = sum(x[0] for x in self.rsi_seed) / n
                self.rsi_avg_loss = sum(x[1] for x in self.rsi_seed) / n
            else:
                self.rsi_avg_gain = (self.rsi_avg_gain * (n - 1) + g) / n
                self.rsi_avg_loss = (self.rsi_avg_loss * (n - 1) + l) / n
            ag, al = self.rsi_avg_gain, self.rsi_avg_loss
        if al == 0:
            self.rsi_value = 100.0
        else:
            self.rsi_value = 100.0 - 100.0 / (1.0 + ag / al)

    def _red_streak(self, t):
        closes, opens = self.closes[t], self.opens[t]
        k = 0
        i = len(closes) - 1
        while i >= 1:
            if self.p["b_red_def"] == "open_close":
                red = closes[i] < opens[i]
            elif self.p["b_red_def"] == "prev_close_le":
                red = closes[i] <= closes[i - 1]
            else:
                red = closes[i] < closes[i - 1]
            if red:
                k += 1
                i -= 1
            else:
                break
        return k

    # ---------- data plumbing ----------

    def OnData(self, data):
        # LOT RECONCILIATION (replaces the v2 split sync, which was applied
        # unconditionally and in an unverified direction: it multiplied the
        # private counter by 7 at the 2014 AAPL split even in adjusted mode,
        # where LEAN does NOT rescale holdings — 694 of 4,086 oracle runs then
        # sold 7x their lot and held an impossible short. Caught by opus-2 R2.
        # In T1 exactly one strategy trades each ticker, so the PORTFOLIO
        # POSITION *is* that strategy's owned lot: take reality as truth every
        # bar, in every normalization mode, with no split arithmetic at all.
        # lot_open / pending stay flag-based: they encode the strategy's own
        # bookkeeping (the same-bar re-entry convention), not ownership.)
        # round, never truncate: after a 7:1 split LEAN can report 237.9999,
        # and int() would leave one share behind and never close the lot
        self.a_shares = max(int(round(float(self.Portfolio[self.syms["SPY"]].Quantity))), 0)
        self.b_shares = max(int(round(float(self.Portfolio[self.syms["AAPL"]].Quantity))), 0)

        mb = self.p["missing_bar"]
        have = [t for t in self.tickers if data.Bars.ContainsKey(self.syms[t])]
        if not have:
            return  # auxiliary slice (no bars): nothing to update or evaluate
        all_present = len(have) == len(self.tickers)

        # state update: present tickers ALWAYS update history (the contract
        # skips RULE EVALUATION on a missing-bar day, not market-state
        # computation); no_guard reads blindly and crashes; try_except is
        # atomic (compute, then commit)
        if mb == "no_guard":
            for t in self.tickers:
                bar = data.Bars[self.syms[t]]  # KeyError on a missing ticker
                self.closes[t].append(float(bar.Close)); self.opens[t].append(float(bar.Open))
        elif mb == "try_except":
            try:
                upd = [(t, float(data.Bars[self.syms[t]].Close), float(data.Bars[self.syms[t]].Open))
                       for t in self.tickers]
            except KeyError:
                return
            for t, c, o in upd:
                self.closes[t].append(c); self.opens[t].append(o)
        else:  # skip_all / per_ticker
            for t in have:
                bar = data.Bars[self.syms[t]]
                self.closes[t].append(float(bar.Close)); self.opens[t].append(float(bar.Open))

        if "SPY" in have:
            if self.p["a_ma_type"] == "EMA":
                self._update_ema(self.closes["SPY"], self.p["a_ma_period"])
        if "AAPL" in have:
            self._update_rsi(self.closes["AAPL"])

        self.bar_index += 1
        if self.IsWarmingUp:
            return
        if mb == "skip_all" and not all_present:
            return  # rule evaluation skipped for the day
        wu = self.p["dof_warmup"]
        if wu == "ready_check" and not (self._ready_a() and self._ready_b()):
            return
        self._evaluate_rules(have)

    # ---------- rule evaluation ----------

    def _a_ok(self):
        return self.p["dof_warmup"] != "ready_per_rule" or self._ready_a()

    def _b_ok(self):
        return self.p["dof_warmup"] != "ready_per_rule" or self._ready_b()

    def _evaluate_rules(self, have):
        sm = self.p["slot_mode"]
        if sm == "sequence":
            self._evaluate_sequence(); return
        buys_first = self.p.get("eval_order", "sells_first") == "buys_first"
        if sm == "race":
            self._a_sell(); self._b_sell()
            if self.race_owner is not None:
                owner_open = self.a_lot_open if self.race_owner == "A" else self.b_lot_open
                if not owner_open:
                    self.race_owner = None
                return
            if self._a_ok() and self._a_buy_reason() and self._reentry_ok("A"):
                self._a_buy()
                if self.a_lot_open: self.race_owner = "A"
                return
            if self._b_ok() and self._b_buy_reason() and self._reentry_ok("B"):
                self._b_buy()
                if self.b_lot_open: self.race_owner = "B"
            return
        # parallel
        if buys_first:
            self._buys(); self._a_sell(); self._b_sell()
        else:
            self._a_sell(); self._b_sell(); self._buys()

    def _buys(self):
        if self._a_ok() and self._a_may_buy() and self._a_buy_reason() and self._reentry_ok("A"):
            self._a_buy()
        if self._b_ok() and self._b_may_buy() and self._b_buy_reason() and self._reentry_ok("B"):
            self._b_buy()

    def _evaluate_sequence(self):
        # Registered SEQUENCE convention (sol-1 R1 #26, frozen jointly):
        # round-trip COMPLETION = the lot back to empty (on the SELL FILL under
        # wait_bar; at sell SUBMISSION under 'allowed'), and the handoff is
        # IMMEDIATE — the newly eligible slot is evaluated in the SAME bar's
        # evaluation (only RACE says "re-opens the next bar").
        for _ in range(2):  # at most one handoff per bar
            if self.seq_eligible == 1:
                self._a_sell()
                if self.seq_was_nonempty and not self.a_lot_open:
                    self.seq_eligible, self.seq_was_nonempty = 2, False
                    continue
                if self._a_ok() and not self.a_lot_open and self._a_buy_reason() and self._reentry_ok("A"):
                    self._a_buy()
                    if self.a_lot_open: self.seq_was_nonempty = True
                return
            else:
                self._b_sell()
                if self.seq_was_nonempty and not self.b_lot_open:
                    self.seq_eligible, self.seq_was_nonempty = 1, False
                    continue
                if self._b_ok() and not self.b_lot_open and self._b_buy_reason() and self._reentry_ok("B"):
                    self._b_buy()
                    if self.b_lot_open: self.seq_was_nonempty = True
                return

    def _reentry_ok(self, which):
        # Behavioral: 'allowed' = the program's OWN bookkeeping marks the lot
        # empty at sell SUBMISSION (a same-bar rebuy is possible); 'wait_bar'
        # = the lot is considered held until the sell FILLS (Portfolio-state
        # reading), so the earliest rebuy is the next bar. Implemented in
        # _a_sell/_b_sell via lot_open; nothing further to gate here.
        return True

    def _a_may_buy(self):
        mode = self.p["lots"]
        if mode == "private":
            return not self.a_lot_open
        if mode == "invested_gate":
            return not self.Portfolio[self.syms["SPY"]].Invested and self.a_pending == 0
        if mode == "shared_flag":   # OM-C shared-state: ONE in-position flag for both slots
            return not (self.a_lot_open or self.b_lot_open)
        return True  # netting

    def _b_may_buy(self):
        mode = self.p["lots"]
        if mode == "private":
            return not self.b_lot_open
        if mode == "invested_gate":
            return not self.Portfolio[self.syms["AAPL"]].Invested and self.b_pending == 0
        if mode == "shared_flag":
            return not (self.a_lot_open or self.b_lot_open)
        return True

    # ---------- Strategy A ----------

    def _a_cross(self, direction, period=None, kind=None):
        closes = self.closes["SPY"]
        period = period or self.p["a_ma_period"]
        kind = kind or self.p["a_ma_type"]
        if len(closes) < 2:
            return False
        ma_y, ma_t = self._ma_pair(closes, period, kind)
        if self.p["dof_cross_timing"] == "today_ma":
            ma_y = ma_t  # both closes tested against TODAY's MA
        return self._crossed(closes[-2], closes[-1], ma_y, ma_t, direction)

    def _ma_x_ma_cross(self, p_short, p_long, direction):
        closes = self.closes["SPY"]
        s_y, s_t = self._ma_pair(closes, p_short, "SMA")
        l_y, l_t = self._ma_pair(closes, p_long, "SMA")
        return self._crossed(s_y, s_t, l_y, l_t, direction)

    def _a_buy_reason(self):
        if self.p["er01_sell"] != "none":
            return self._a_cross("up", period=200, kind="SMA")
        return self._a_cross(self.p["a_buy_dir"])

    def _a_sell_reason(self):
        er = self.p["er01_sell"]
        if er == "none":
            return self._a_cross(self.p["a_sell_dir"])
        return {
            "R1": lambda: self._a_cross("down", period=50, kind="SMA"),
            "R2": lambda: self._a_cross("up", period=50, kind="SMA"),
            "R3": lambda: self._ma_x_ma_cross(50, 200, "down"),
            "R4": lambda: self._ma_x_ma_cross(50, 200, "up"),
            "R5": lambda: self._a_cross("any", period=50, kind="SMA"),
            "R6": lambda: self._ma_x_ma_cross(50, 200, "any"),
        }[er]()

    def _a_buy(self):
        px = self.closes["SPY"][-1]
        tpv = float(self.Portfolio.TotalPortfolioValue)
        pct = self.p["a_size_pct"] / 100.0
        if self.p["dof_a_exec"] == "set_holdings":
            before = int(self.Portfolio[self.syms["SPY"]].Quantity)
            self.SetHoldings(self.syms["SPY"], pct)
            # SetHoldings submits only if the target differs; detect via tickets
            submitted = any(t.Symbol == self.syms["SPY"] and t.Status not in (OrderStatus.Filled, OrderStatus.Canceled, OrderStatus.Invalid)
                            for t in self.Transactions.GetOpenOrderTickets())
            if not submitted:
                return
            self.a_pending = 1  # quantity unknown until fill; marker only
        else:
            base = float(self.Portfolio.Cash) if self.p["dof_a_exec"] == "pct_cash" else tpv
            shares = int(math.floor(base * pct / px))
            if shares <= 0:
                return
            self.MarketOrder(self.syms["SPY"], shares)
            self.a_pending += shares
        self.a_lot_open = True
        self.a_last_action_bar = self.bar_index

    def _a_holding(self):
        if self.p["lots"] == "private":
            return self.a_shares
        return max(int(self.Portfolio[self.syms["SPY"]].Quantity), 0)

    def _a_sell(self):
        held = self._a_holding()
        if held <= 0 or not self._a_ok() or not self._a_sell_reason():
            return
        frac = self.p["a_sell_frac"]
        if frac == "all":
            qty = held
        elif frac == "half_down_lastsell":
            qty = 1 if held == 1 else held // 2
        elif frac == "half_down_hold":
            qty = held // 2
        elif frac == "half_up":
            qty = (held + 1) // 2
        else:
            raise ValueError(frac)
        if qty > 0:
            self.MarketOrder(self.syms["SPY"], -qty)
            self.a_pending -= qty
            self.a_last_action_bar = self.bar_index
            if qty >= held and self.p["dof_same_bar_reentry"] == "allowed":
                self.a_lot_open = False  # own bookkeeping: lot empty at submission

    # ---------- Strategy B ----------

    def _b_buy_reason(self):
        return self._red_streak("AAPL") >= self.p["b_red_days"]

    def _b_sell_reason(self):
        if self.rsi_value is None:
            return False
        th = self.p["b_rsi_thresh"]
        if self.p["dof_rsi_exit"] == "cross":
            return self.rsi_prev is not None and self.rsi_prev <= th and self.rsi_value > th
        return self.rsi_value > th

    def _b_buy(self):
        px = self.closes["AAPL"][-1]
        cash = float(self.Portfolio.Cash)
        amt = self.p["b_cash_amt"]
        rule = self.p["b_cash_rule"]
        if rule == "skip":
            if cash < amt:
                return
            shares = int(math.floor(amt / px))
        elif rule == "partial":
            shares = int(math.floor(min(cash, amt) / px))
        else:
            shares = int(math.floor(amt / px))
        if shares > 0:
            self.MarketOrder(self.syms["AAPL"], shares)
            self.b_pending += shares
            self.b_lot_open = True
            self.b_last_action_bar = self.bar_index

    def _b_sell(self):
        held = self.b_shares if self.p["lots"] == "private" else max(int(self.Portfolio[self.syms["AAPL"]].Quantity), 0)
        if held <= 0 or not self._b_ok() or not self._b_sell_reason():
            return
        self.MarketOrder(self.syms["AAPL"], -held)
        self.b_pending -= held
        self.b_last_action_bar = self.bar_index
        if self.p["dof_same_bar_reentry"] == "allowed":
            self.b_lot_open = False  # own bookkeeping: lot empty at submission

    # ---------- fill sync (both signs; partial fills accumulate) ----------

    def OnOrderEvent(self, e):
        sym = str(e.Symbol)
        is_a = "SPY" in sym
        is_b = "AAPL" in sym
        if not (is_a or is_b):
            return
        if e.Status in (OrderStatus.Filled, OrderStatus.PartiallyFilled):
            q = int(e.FillQuantity)
            if is_a:
                self.a_shares += q
                if self.p["dof_a_exec"] == "set_holdings" and q > 0:
                    self.a_pending = 0
                else:
                    self.a_pending -= q
                # lot closes on the SELL FILL only if no rebuy is pending
                # (under 'allowed' a same-bar rebuy may already be in flight)
                if e.Status == OrderStatus.Filled and self.a_shares <= 0 and self.a_pending <= 0:
                    self.a_shares = 0; self.a_lot_open = False; self.a_pending = 0
            else:
                self.b_shares += q
                self.b_pending -= q
                if e.Status == OrderStatus.Filled and self.b_shares <= 0 and self.b_pending <= 0:
                    self.b_shares = 0; self.b_lot_open = False; self.b_pending = 0
        elif e.Status in (OrderStatus.Invalid, OrderStatus.Canceled):
            if is_a:
                self.a_pending = 0
                if self.a_shares == 0:
                    self.a_lot_open = False
            else:
                self.b_pending = 0
                if self.b_shares == 0:
                    self.b_lot_open = False
