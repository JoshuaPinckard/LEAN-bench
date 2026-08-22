"""Mechanical extractor v2 — CODEBOOK-v2 SSB/SSC (vetting-council round 1).
AST-first, comment/docstring-stripped, BEHAVIORAL rules:
  A1 rsi_smoothing  wilder|simple|ema|unresolved
  A2 warmup         strict|ready_check|ready_per_rule|none  (+ warmup_bars)
  A3 a_exec         set_holdings|calc_shares|pct_cash|unresolved  (magnitude-independent)
  A4 same_bar_reentry allowed|wait_bar|unresolved   (fill-state gating => wait_bar)
  A5 input_field    adjusted|raw|split_adjusted|total_return
  A6 cross_dirs     buy_dir/sell_dir in {up, down, any, level}
  A7 rsi_exit       level|cross
  A8 cross_timing   both_days|today_ma
  C  numeric(blank) -> {value, comparator, status}; names resolved through
     single-assignment constants; comparator recorded (never silently
     normalized); exact decimal parse; two distinct candidates -> unresolved.
Anything the rules cannot decide returns 'unresolved' (never a guess).
The extractor NEVER gates tape matching (SS4.4 v2: tuple-free lookup); it
feeds the SS4.7 validity report, no-cue coding, and numeric codes.
"""
import ast
import io as _io
import re
import sys
import tokenize as _tokenize
from decimal import Decimal, InvalidOperation
from pathlib import Path

# ---------------------------------------------------------------- helpers

def strip_comments(text):
    """Back-compat name. Returns the sanitized text only; a caller that needs
    to know whether sanitizing SUCCEEDED must use sanitize()."""
    return sanitize(text)[0]


_NUMERIC_STRING = re.compile(r"^\s*[-+]?\d+(?:\.\d+)?\s*$")
_STRING_SHAPE = re.compile("^([A-Za-z]*)(" + "'''" + '|"""' + "|'" + '|")([\\s\\S]*)\\2$')
# 3.12+ (PEP 701) lexes f-strings as FSTRING_START/MIDDLE/END rather than one
# STRING token, so the payload is resolved dynamically and blanked on both.
_TK_FSTRING_MIDDLE = getattr(_tokenize, "FSTRING_MIDDLE", None)


def sanitize(text):
    """-> (text with comment bodies, string payloads and ERRORTOKEN payloads removed, ok).

    ONE tokenize pass (comments, strings, ERRORTOKEN, f-string bodies together).
    Replaces three exploitable layers: a hand-rolled '#' stripper with no
    escape awareness, a triple-quote regex that spliced across ordinary
    literals, and a per-token numeric carve-out defeated by implicit
    concatenation. A STRING adjacent to another STRING is treated as prose;
    a literal whose ENTIRE content is numeric is preserved (Decimal("0.40")
    is a value, not prose). ok=False => the caller must refuse, never scan
    raw text."""
    try:
        toks = list(_tokenize.generate_tokens(_io.StringIO(text).readline))
    except Exception:
        return "", False

    # A STRING adjacent to another STRING is implicit concatenation, so no
    # single token carries the value; both are treated as prose regardless of
    # content. That closes the carve-out without eating Decimal("0.40").
    skip = (_tokenize.NL, _tokenize.NEWLINE, _tokenize.COMMENT, _tokenize.INDENT, _tokenize.DEDENT)
    sig = [i for i, t in enumerate(toks) if t.type not in skip]
    concat = set()
    for a, b in zip(sig, sig[1:]):
        if toks[a].type == _tokenize.STRING and toks[b].type == _tokenize.STRING:
            concat.add(a)
            concat.add(b)

    lines = text.splitlines(keepends=True)
    out = []
    pos = (1, 0)

    def upto(end):
        (sr, sc), (er, ec) = pos, end
        if sr == er:
            return lines[sr - 1][sc:ec] if sr - 1 < len(lines) else ""
        chunk = lines[sr - 1][sc:] if sr - 1 < len(lines) else ""
        for r in range(sr, er - 1):
            chunk += lines[r] if r < len(lines) else ""
        chunk += lines[er - 1][:ec] if er - 1 < len(lines) else ""
        return chunk

    for i, t in enumerate(toks):
        out.append(upto(t.start))
        if t.type == _tokenize.ERRORTOKEN:
            # An unterminated string does NOT raise on CPython 3.11: tokenize
            out.append("\n" * t.string.count("\n"))
        elif t.type == _tokenize.COMMENT:
            out.append("#")                      # marker kept, payload dropped
        elif _TK_FSTRING_MIDDLE is not None and t.type == _TK_FSTRING_MIDDLE:
            out.append("\n" * t.string.count("\n"))
        elif t.type == _tokenize.STRING:
            raw = t.string
            m = _STRING_SHAPE.match(raw)
            keep = bool(m) and i not in concat and bool(_NUMERIC_STRING.match(m.group(3) or ""))
            if m and not keep:
                out.append(m.group(1) + m.group(2) + ("\n" * raw.count("\n")) + m.group(2))
            else:
                out.append(raw)
        else:
            out.append(t.string)
        pos = t.end
    return "".join(out), True


def parse(text):
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def const_table(tree):
    """name -> numeric literal for single-assignment constants:
    module-level `X = 3`, and `self.X = 3` anywhere (last assignment wins
    only if all assignments agree; else ambiguous -> dropped). A plain-name
    constant X additionally answers for `self.X` when NO assignment to
    `self.X` (of any kind, numeric or not) exists — Python's class-attribute
    fallback for a program that executed (X1: `SMA_PERIOD = 20` at class
    level read as `self.SMA_PERIOD`, 5/10 real codex probe programs). Any
    `self.X` assignment, even non-numeric, blocks the alias: the instance
    value shadows the class constant and cannot be read statically."""
    tab, bad = {}, set()
    if tree is None:
        return tab
    self_assigned = set()
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                self_assigned.add(t.attr)
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            name = None
            if isinstance(t, ast.Name):
                name = t.id
            elif isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                name = "self." + t.attr
            if name is None:
                continue
            v = _num_of(node.value)
            if v is None:
                continue
            if name in tab and tab[name] != v:
                bad.add(name)
            tab[name] = v
    for b in bad:
        tab.pop(b, None)
    for name in [n for n in tab if "." not in n]:
        if name not in self_assigned and ("self." + name) not in tab:
            tab["self." + name] = tab[name]
    return tab


def _num_of(node):
    """Numeric value of a literal / Decimal("x") / unary minus, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return Decimal(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _num_of(node.operand); return -v if v is not None else None
    if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "Decimal" and node.args:
        a = node.args[0]
        if isinstance(a, ast.Constant):
            try: return Decimal(str(a.value))
            except InvalidOperation: return None
    return None


def _name_of(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return "self." + node.attr
    return None


def resolve_num(node, tab):
    v = _num_of(node)
    if v is not None:
        return v
    n = _name_of(node)
    if n and n in tab:
        return tab[n]
    return None


def src(node, text):
    try:
        return ast.get_source_segment(text, node) or ""
    except Exception:
        return ""

# ---------------------------------------------------------------- A-rules

def rsi_smoothing(text, tree):
    t = text
    if re.search(r"MovingAverageType\.Simple", t): return "simple"
    if re.search(r"MovingAverageType\.Exponential", t): return "ema"
    if re.search(r"MovingAverageType\.Wilders", t): return "wilder"
    if re.search(r"\b(self\.)?RSI\s*\(|RelativeStrengthIndex\s*\(|\bself\.rsi\s*\(", t):
        return "wilder"  # LEAN default MovingAverageType for RSI is Wilders
    if re.search(r"\(\s*\w+\s*\*\s*\(\s*\w+\s*-\s*1\s*\)\s*\+\s*\w+\s*\)\s*/\s*\w+", t):
        return "wilder"
    if re.search(r"(gain|loss)\w*[^\n]{0,80}(sum\(|mean\(|rolling\()", t, re.I) or re.search(r"(sum\(|mean\()[^\n]{0,40}(gain|loss)", t, re.I):
        return "simple"
    if re.search(r"ewm\(|(gain|loss)\w*[^\n]{0,60}\*\s*\(\s*1\s*-\s*\w+\s*\)", t, re.I):
        return "ema"
    return "unresolved"


def warmup(text, tree):
    """Behavioral A2: strict = SetWarmUp present (any length; IsReady checks
    irrelevant); ready_check = no SetWarmUp, ONE global readiness gate at
    the top of OnData (early return); ready_per_rule = no SetWarmUp,
    readiness tested inside strategy-specific conditions; none = neither."""
    m = re.search(r"(?:SetWarmUp|set_warm_up)\s*\(\s*([^,)]+)", text)
    bars = None
    if m:
        arg = m.group(1).strip()
        mm = re.match(r"(\d+)$", arg)
        if mm: bars = int(mm.group(1))
        elif "timedelta" in arg:
            mm2 = re.search(r"days\s*=\s*(\d+)", arg); bars = ("days", int(mm2.group(1))) if mm2 else "timedelta"
        else:
            bars = arg[:40]
        return "strict", bars
    has_ready = re.search(r"\.IsReady\b|\.is_ready\b|len\(\s*self\.\w+\s*\)\s*<", text) is not None
    if not has_ready:
        return "none", None
    # global vs per-rule: an early `return` at OnData top level guarded by a
    # readiness test — directly, or through a helper method whose body
    # tests readiness (e.g. `if not self._ready(): return`)
    if tree is not None:
        funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        def tests_ready(expr):
            s = src(expr, text)
            if re.search(r"IsReady|is_ready|len\(", s):
                return True
            for c in ast.walk(expr):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in funcs:
                    if re.search(r"IsReady|is_ready|len\(", src(funcs[c.func.attr], text)):
                        return True
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in ("OnData", "on_data"):
                for st in node.body:
                    if isinstance(st, ast.If) and tests_ready(st.test) and any(isinstance(x, ast.Return) for x in ast.walk(st)):
                        return "ready_check", None
    return "ready_per_rule", None


def a_exec(text, tree):
    # SetHoldings on the A ticker with ANY numeric/variable second argument
    if re.search(r"(?:SetHoldings|set_holdings)\s*\(\s*[^,]*(?:SPY|spy|_a\b|a_sym|symbol_a)[^,]*,\s*[^)]+\)", text, re.I) or \
       re.search(r"(?:SetHoldings|set_holdings)\s*\(\s*[^,]*,\s*[^)]+\)", text):
        # if the file also has explicit share arithmetic for SPY, prefer the mechanism nearest 'SPY'
        pass
    sh = re.search(r"(?:SetHoldings|set_holdings)\s*\(", text) is not None
    tpv = re.search(r"TotalPortfolioValue|total_portfolio_value", text) is not None
    cash = re.search(r"Portfolio\.Cash\b|portfolio\.cash\b", text) is not None
    mo = re.search(r"MarketOrder\s*\(|market_order\s*\(", text) is not None
    if sh and not (tpv and mo):
        return "set_holdings"
    if tpv and mo:
        return "calc_shares"
    if cash and mo and not tpv:
        return "pct_cash" if re.search(r"Cash\b[^\n]{0,60}\*|\*[^\n]{0,60}Cash\b", text) else "unresolved"
    if sh:
        return "set_holdings"
    return "unresolved"


def same_bar_reentry(text, tree):
    """Behavioral A4. wait_bar if the A/B BUY gate reads fill-based state
    (Portfolio[..].Invested / .Quantity / HoldStock / IsLong) or the buy
    branch is structurally unreachable on the sell bar (elif/else/return);
    allowed if the buy gate reads an OWN flag/counter that the sell branch
    resets at submission; else unresolved."""
    t = text
    if re.search(r"Portfolio\s*\[[^\]]+\]\s*\.\s*(Invested|Quantity|HoldStock|IsLong|invested|quantity)", t):
        return "wait_bar"
    if re.search(r"last[_ ]?(action|trade|sell|exit)[_ ]?(bar|date|day|time)", t, re.I) or re.search(r"(sold|sell)[_]?(today|this[_]?bar)", t, re.I):
        return "wait_bar"
    # structural: sell branch and buy branch in if/elif or if/else
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                body_src = " ".join(src(s, t) for s in node.body)
                else_src = " ".join(src(s, t) for s in node.orelse)
                if re.search(r"Liquidate|MarketOrder\([^)]*-|Sell|sell", body_src) and re.search(r"MarketOrder|SetHoldings|Buy|buy", else_src):
                    return "wait_bar"
    # own-flag pattern: a shares/lot/holding variable compared to 0 / False as the buy gate,
    # and set to 0/False in the sell branch
    if re.search(r"(shares|lot|holding|position|qty|units)\w*\s*(==\s*0|<=\s*0|is\s+None|==\s*False)|not\s+self\.\w*(in_position|holding|long|has_position)\w*", t, re.I) and \
       re.search(r"(shares|lot|holding|position|qty|units)\w*\s*=\s*0\b|self\.\w*(in_position|holding|long|has_position)\w*\s*=\s*False", t, re.I):
        return "allowed"
    if re.search(r"Liquidate\s*\(|MarketOrder\s*\(", t):
        return "unresolved"
    return "unresolved"


def input_field(text, tree):
    if re.search(r"DataNormalizationMode\.Raw", text): return "raw"
    if re.search(r"DataNormalizationMode\.SplitAdjusted", text): return "split_adjusted"
    if re.search(r"DataNormalizationMode\.TotalReturn", text): return "total_return"
    return "adjusted"


def rsi_aliases(text, tree):
    """Names assigned from an RSI value expression (e.g. cur = self.rsi.Current.Value)."""
    names = set()
    if tree is None:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            n = _name_of(node.targets[0])
            if n and re.search(r"rsi", src(node.value, text), re.I):
                names.add(n.split(".")[-1])
    return names


def rsi_exit(text, tree):
    """A7: 'cross' if the RSI condition compares BOTH a previous and a current
    RSI value against the threshold (prev <= T and cur > T); else 'level'."""
    al = "|".join(sorted(rsi_aliases(text, tree) | {"rsi"}))
    cur = r"(?:\w*(?:%s)\w*)" % al
    if re.search(r"(prev|previous|last|yesterday)\w*[^\n]{0,60}(<=|<)[^\n]{0,80}\b" + cur + r"[^\n]{0,40}>", text, re.I) or \
       re.search(r"\b" + cur + r"[^\n]{0,40}>\s*[^\n]{0,60}and[^\n]{0,60}(prev|previous|last|yesterday)\w*[^\n]{0,40}(<=|<)", text, re.I) or \
       re.search(r"rsi\w*\[\s*1\s*\][^\n]{0,60}(<=|<)[^\n]{0,60}rsi\w*\[\s*0\s*\][^\n]{0,40}>", text, re.I):
        return "cross"
    if re.search(r"\brsi\b|RSI", text):
        return "level"
    return "unresolved"


def cross_timing(text, tree):
    """A8: both_days if a PREVIOUS MA value is kept and used (window/prev
    variable/Previous property); today_ma if yesterday's close is compared
    to today's MA only."""
    if re.search(r"(prev|previous|last|yesterday)\w*(sma|ma|average)\w*|(sma|ma|average)\w*(prev|previous|last|yesterday)\w*|\.Previous\b|RollingWindow[^\n]{0,80}(sma|ma)|(sma|ma)_window|ma\[\s*1\s*\]|sma\[\s*1\s*\]", text, re.I):
        return "both_days"
    if re.search(r"(sma|moving|average)", text, re.I):
        return "today_ma"
    return "unresolved"


def cross_dirs(text, tree):
    """A6: buy/sell direction for A. Returns (buy_dir, sell_dir)."""
    def d(kind):
        pat = r"(buy|entry|enter|long)" if kind == "buy" else r"(sell|exit|liquidat)"
        seg = ""
        for m in re.finditer(pat + r"[^\n]{0,200}", text, re.I):
            seg += m.group(0) + " "
        up = re.search(r"cross\w*\s*(above|over|up)|>\s*[^\n]{0,30}(sma|ma|average)|(above|over)", seg, re.I) is not None
        dn = re.search(r"cross\w*\s*(below|under|down)|<\s*[^\n]{0,30}(sma|ma|average)|(below|under)", seg, re.I) is not None
        if up and dn: return "any"
        if up: return "up"
        if dn: return "down"
        return "unresolved"
    return d("buy"), d("sell")

# ---------------------------------------------------------------- C numeric

# The `(?!\s*\.\s*\d)` guard is load-bearing: without it the integer prefix of
_INT_ARG = re.compile(r"\s*(?:(?:\"[^\"]*\"|'[^']*'|[A-Za-z_][\w\.\[\]\"']*)\s*,\s*)?([A-Za-z_][\w\.]*|\d{1,4}(?!\s*\.\s*\d))\b")

def _first_int_arg(pattern, text, tab):
    out = []
    for m in re.finditer(pattern, text, re.I):
        seg = text[m.end(): m.end() + 80]
        mm = _INT_ARG.match(seg)
        if not mm:
            continue
        tok = mm.group(1)
        if tok.isdigit():
            out.append(int(tok))
        elif tok in tab and tab[tok] == tab[tok].to_integral_value():
            out.append(int(tab[tok]))
    return out


def _cmp_values(text, tab, lhs_pat):
    """(comparator, Decimal) for comparisons `<lhs> <op> <rhs>` where lhs
    matches lhs_pat and rhs is a literal or resolvable name."""
    out = []
    for m in re.finditer(lhs_pat + r"[^\n<>=!]{0,60}?(>=|<=|>|<|==)\s*(?:Decimal\s*\(\s*[\"']?)?([A-Za-z_][\w\.]*|\d+(?:\.\d+)?)", text, re.I):
        op, tok = m.group(1), m.group(2)
        v = None
        if re.match(r"\d", tok):
            v = Decimal(tok)
        elif tok in tab:
            v = tab[tok]
        if v is not None:
            out.append((op, v))
    return out


def _guard_thresholds(tree, name_re):
    """{(op, Decimal)} for EARLY-RETURN GUARDS on a streak-like name.

    `if self.red_streak < 3: return` implements the rule 'act at >= 3'
    (d3), the opposite of the comparison read in isolation. Guard-ness is
    decided STRUCTURALLY: the comparison is an If test whose body only
    leaves (return/continue/pass). A bare non-guard `<` is left for the
    caller to refuse."""
    out = set()
    if tree is None:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        if not node.body or not all(isinstance(st, (ast.Return, ast.Continue, ast.Pass)) for st in node.body):
            continue
        if any(isinstance(st, ast.Return) and st.value is not None for st in node.body):
            continue                      # `return something` is not a bare guard
        cmp_ = node.test
        if len(cmp_.ops) != 1 or len(cmp_.comparators) != 1:
            continue
        op = cmp_.ops[0]
        if not isinstance(op, (ast.Lt, ast.LtE)):
            continue
        lhs = _name_of(cmp_.left) or ""
        if not re.search(name_re, lhs, re.I):
            continue
        v = _num_of(cmp_.comparators[0])
        if v is None:
            continue
        # guard leaves when cmp is TRUE, so the program acts on its negation:
        #   `< N`  -> acts at >= N      -> required length N
        #   `<= N` -> acts at >= N + 1  -> required length N + 1
        out.add((">=", v if isinstance(op, ast.Lt) else v + 1))
    return out


def numeric(blank, text):
    """-> dict(value=int|None, comparator=str|None, status='ok'|'unresolved'|'no-implementation')"""
    raw = text
    text, ok = sanitize(raw)
    if not ok:
        # unlexable source: refuse rather than regex-scan the raw text
        return {"value": None, "comparator": None, "status": "unresolved", "reason": "not-lexable"}
    # DEFENCE IN DEPTH: a program that does not parse cannot have produced a
    if parse(raw) is None:
        return {"value": None, "comparator": None, "status": "unresolved", "reason": "not-parseable"}
    # const_table walks ASSIGNMENTS on the ORIGINAL tree. That is structural,
    # so prose cannot reach it, and Python has already folded any implicit
    # string concatenation for us.
    tree = parse(raw) or parse(text)
    tab = const_table(tree)
    cands, comps = [], []
    if blank == "BL-01b":
        # DIRECT constructors are unioned so that two of them DISAGREEING
        cands = _first_int_arg(r"\bSMA\s*\(", text, tab) + _first_int_arg(r"SimpleMovingAverage\s*\(", text, tab)
        if not cands:
            cands = _first_int_arg(r"RollingWindow\s*\[\s*float\s*\]\s*\(", text, tab) \
                or _first_int_arg(r"deque\s*\(\s*maxlen\s*=", text, tab)
    elif blank == "BL-03":
        vals = []
        for m in re.finditer(r"(?:SetHoldings|set_holdings)\s*\([^,]*,\s*(?:Decimal\s*\(\s*[\"']?)?([A-Za-z_][\w\.]*|0?\.\d+|\d+(?:\.\d+)?)", text, re.I):
            tok = m.group(1); v = Decimal(tok) if re.match(r"[\d.]", tok) else tab.get(tok)
            if v is not None: vals.append(v)
        for m in re.finditer(r"(?:Decimal\s*\(\s*[\"']?)?(0?\.\d+|\d+(?:\.\d+)?|[A-Za-z_][\w\.]*)[\"']?\s*\)?\s*\*\s*(?:float\s*\()?\s*self\.Portfolio\.TotalPortfolioValue|TotalPortfolioValue\s*\)?\s*\*\s*(?:Decimal\s*\(\s*[\"']?)?(0?\.\d+|\d+(?:\.\d+)?|[A-Za-z_][\w\.]*)", text, re.I):
            tok = m.group(1) or m.group(2)
            v = Decimal(tok) if re.match(r"[\d.]", tok) else tab.get(tok)
            if v is not None: vals.append(v)
        for v in vals:
            # EXACT ONLY. This rounded to the nearest integer percent, so a
            pct = (v * 100) if v <= 1 else v
            cands.append(int(pct) if pct == pct.to_integral_value() else float(pct))
    elif blank == "BL-05":
        # structural early-return guards first: they carry the real threshold
        for gop, gv in _guard_thresholds(tree, r"(?:consecutive|streak|red)"):
            if gv == gv.to_integral_value():
                comps.append(gop); cands.append(int(gv))
        guarded = bool(comps)
        for op, v in _cmp_values(text, tab, r"(?:consecutive|streak|red)[\w\.]*"):
            if v != v.to_integral_value():
                comps.append(op); cands.append(float(v)); continue
            n = int(v)
            if op in ("<", "<="):
                # Already accounted for if this was the guard we just read.
                if guarded:
                    continue
                cands.append(None); comps.append(op)
                continue
            # BL-05 counts CONSECUTIVE DOWN DAYS — a discrete integer. On a
            if op == ">":
                n += 1; op = ">="          # discrete count: `> N` first fires at N+1
            comps.append(op); cands.append(n)
        for m in re.finditer(r"\b(\d{1,2})\s*(<=|==)\s*[\w\.]*(?:consecutive|streak|red)", text, re.I):
            cands.append(int(m.group(1))); comps.append({"<=": ">=", "==": "=="}[m.group(2)])
    elif blank == "BL-08":
        al = "|".join(sorted(rsi_aliases(text, tree) | {"rsi"}))
        for op, v in _cmp_values(text, tab, r"\b(?:\w*(?:%s)\w*)[\w\.\[\]]*" % al):
            if op in (">", ">="):
                comps.append(op); cands.append(int(v) if v == v.to_integral_value() else float(v))
    elif blank == "BL-07":
        # both are direct RSI constructors: union, so a disagreement is
        # refused as unresolved rather than resolved by declaration order
        cands = _first_int_arg(r"\bRSI\s*\(", text, tab) + _first_int_arg(r"RelativeStrengthIndex\s*\(", text, tab)
    elif blank == "PX-01":
        pats = [r"Portfolio\.Cash\s*(?:>=|>)\s*(?:Decimal\s*\(\s*[\"']?)?([A-Za-z_][\w\.]*|\d{1,3}(?:[,_]\d{3})+|\d{4,6})(?:\.0+)?",
                r"(?:cash|amount|dollars|budget|target|notional)\w*\s*=\s*(?:Decimal\s*\(\s*[\"']?)?([A-Za-z_][\w\.]*|\d{1,3}(?:[,_]\d{3})+|\d{4,6})(?:\.0+)?(?!\d)",
                r"int\s*\(\s*(?:Decimal\s*\(\s*[\"']?)?([A-Za-z_][\w\.]*|\d{1,3}(?:[,_]\d{3})+|\d{4,6})(?:\.0+)?\s*/"]
        for p in pats:
            for tok in re.findall(p, text, re.I):
                if re.match(r"[A-Za-z_]", tok):
                    v = tab.get(tok)
                    if v is None: continue
                    v = int(v)
                else:
                    v = int(float(tok.replace(",", "").replace("_", "")))
                if 1000 <= v <= 200000:
                    cands.append(v)
    if not cands:
        # distinguish 'pattern not found but leg present' from 'leg absent'
        leg_present = {"BL-01b": r"SMA|SimpleMoving|moving", "BL-03": r"SetHoldings|TotalPortfolioValue", "BL-05": r"red|streak|consecutive",
                       "BL-08": r"rsi", "BL-07": r"rsi", "PX-01": r"AAPL"}[blank]
        return {"value": None, "comparator": None, "status": "unresolved" if re.search(leg_present, text, re.I) else "no-implementation"}
    if any(c is None for c in cands):
        # an unclassifiable comparison form: refuse rather than code a guess
        return {"value": None, "comparator": None, "status": "unresolved",
                "reason": "ambiguous-comparator-direction"}
    distinct = sorted(set(cands))
    if len(distinct) > 1:
        return {"value": None, "comparator": None, "status": "unresolved", "candidates": distinct}
    comp = sorted(set(comps))
    return {"value": distinct[0], "comparator": (comp[0] if len(comp) == 1 else (None if not comp else "mixed")), "status": "ok"}

# ---------------------------------------------------------------- API

def extract(text_raw):
    text = strip_comments(text_raw)
    tree = parse(text)
    wu, wb = warmup(text, tree)
    bd, sd = cross_dirs(text, tree)
    return {
        "dof_rsi_smoothing": rsi_smoothing(text, tree),
        "dof_warmup": wu, "warmup_bars": wb,
        "dof_a_exec": a_exec(text, tree),
        "dof_same_bar_reentry": same_bar_reentry(text, tree),
        "dof_input_field": input_field(text, tree),
        "dof_rsi_exit": rsi_exit(text, tree),
        "dof_cross_timing": cross_timing(text, tree),
        "a_buy_dir": bd, "a_sell_dir": sd,
        "parsed": tree is not None,
    }


if __name__ == "__main__":
    import json
    for p in sys.argv[1:]:
        t = Path(p).read_text(encoding="utf-8", errors="replace")
        print(p, json.dumps(extract(t)))
