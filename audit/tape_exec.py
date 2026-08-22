"""Tape-instrumented replica of QuantCode-Bench's execution stack.

Reproduces their wrapper exactly (Cerebro, cash 10000, commission 0.001,
bt.feeds.PandasData from the pickle cache, TradeAnalyzer) and adds a
TapeRecorder analyzer logging every completed order as
(iso-datetime, BUY/SELL, size, price). The tape — (timestamp, side) — is the
exact ground truth their judge never sees.

Usage: python tape_exec.py <strategy.py> <cache.pkl>   -> prints JSON result
Import: run_tape(strategy_code, cache_path) -> dict
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

WRAPPER = '''
{strategy_code}

import sys, json, pickle
import backtrader as bt

class TapeRecorder(bt.Analyzer):
    def start(self):
        self.tape = []
    def notify_order(self, order):
        if order.status == order.Completed:
            self.tape.append({{
                "dt": bt.num2date(order.executed.dt).isoformat(),
                "side": "BUY" if order.isbuy() else "SELL",
                "size": float(order.executed.size),
                "price": float(order.executed.price),
            }})
    def get_analysis(self):
        return self.tape

def run_backtest():
    strategy_class = None
    for name in list(globals().keys()):
        try:
            obj = globals()[name]
            if isinstance(obj, type) and issubclass(obj, bt.Strategy) and obj != bt.Strategy:
                strategy_class = obj
                break
        except (TypeError, AttributeError):
            continue
    if strategy_class is None:
        return {{"success": False, "error": "No strategy class found"}}
    try:
        with open(r"{cache_path}", "rb") as f:
            df = pickle.load(f)
        if df.empty:
            return {{"success": False, "error": "Empty data"}}
    except Exception as e:
        return {{"success": False, "error": "Data loading error: " + str(e)}}
    try:
        cerebro = bt.Cerebro()
        cerebro.addstrategy(strategy_class)
        data_feed = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data_feed)
        cerebro.broker.setcash(10000)
        cerebro.broker.setcommission(commission=0.001)
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        cerebro.addanalyzer(TapeRecorder, _name="tape")
        start_value = cerebro.broker.getvalue()
        results = cerebro.run()
        end_value = cerebro.broker.getvalue()
        strat = results[0]
        trades = strat.analyzers.trades.get_analysis()
        total_trades = trades.get("total", {{}}).get("total", 0) if trades else 0
        return {{
            "success": True,
            "has_trades": total_trades > 0,
            "total_trades": total_trades,
            "total_return": (end_value - start_value) / start_value * 100 if start_value > 0 else 0,
            "tape": strat.analyzers.tape.get_analysis(),
        }}
    except Exception as e:
        return {{"success": False, "error": "Backtest error: " + str(e)}}

print(json.dumps(run_backtest()))
'''


def run_tape(strategy_code, cache_path, timeout=120):
    code = WRAPPER.format(strategy_code=strategy_code, cache_path=cache_path)
    try:
        p = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout"}
    if p.returncode != 0:
        return {"success": False,
                "error": "\n".join(p.stderr.strip().splitlines()[-8:])}
    for line in reversed(p.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except Exception:
                pass
    return {"success": False, "error": "no JSON output"}


def tape_key(tape):
    """(timestamp, side) sequence — the graded ground truth."""
    return [(e["dt"], e["side"]) for e in tape]


if __name__ == "__main__":
    code = Path(sys.argv[1]).read_text(encoding="utf-8")
    r = run_tape(code, sys.argv[2])
    print(json.dumps({k: (v if k != "tape" else v[:8]) for k, v in r.items()},
                     indent=2))
