"""Generate the frozen v5 variants per PIN-v5-2026-08-15 SS3.1/3.2.
16 T1v0-derived variants + ER-01 (second donor) + OM-A/B/C.
Byte-exact spans; asserts occurrence counts, no orphan list markers,
no dangling punctuation, defined-term bindings; emits
rung2/variants-v5.json with SHA-256 per variant.
"""
import hashlib
import json
import sys
from pathlib import Path

OUT = Path(r"C:\Users\joshp\Desktop\LEAN-Bench-Research\rung2")
DONOR_SHA = "6cf7509fb7fc6fb8de608b447be313017a6e0a26c352db3c9636effbcb77f8d5"
# The COMMITTED donor (not the mutable prompt package behind a junction);
# a moved or altered donor fails loudly instead of silently re-freezing.
BASE = (OUT / "T1v0.txt").read_text(encoding="utf-8")
assert hashlib.sha256(BASE.encode("utf-8")).hexdigest() == DONOR_SHA, "donor T1v0.txt hash != registered"

SMA = "its 100-day simple moving average"
CROSS_BULLET = '- "X crosses above Y" means: yesterday X was less than or equal to Y, and today X is greater than Y (both evaluated with that day\'s values). "Crosses below" is the mirror image. A level being above/below is NOT a cross.\n'
BUY_LINE = "Reason to buy: SPY's close crosses above its 100-day simple moving average."
SELL_LINE = "Reason to sell: SPY's close crosses below its 100-day simple moving average."
RED_DEF = 'A "red day" for a ticker means its close is strictly below the PREVIOUS day\'s close. A "green day" means strictly above. '
B06_BODY_OLD = "buy $20,000 of AAPL if at least $20,000 cash is available, otherwise do nothing."
B06_BODY_NEW = "buy $20,000 of AAPL if available."
B06_CON_OLD = "shares; otherwise do NOTHING this bar (the strategy stays flat; the reason may fire again on a later bar)."
B06_CON_NEW = "shares."
SELL_HALF = 'Sell detail "sell half" means sell half of the lot\'s current shares rounded down (sell the last share when only one remains). '
MISSING_BAR = " If today's bar is missing for ANY subscribed ticker, skip ALL rule evaluation for that day (do not crash on missing data)."
LOTS_BULLET = "- Each strategy manages its own private lot of shares in its trade ticker: it sells only shares it bought, and its buy reason is evaluated only while its lot is empty; its sell reason only while its lot is non-empty. On any bar, evaluate sells before buys.\n"
SLOTS_DECL_OLD = "One template with 2 slots, no gate. Both slots run independently in parallel."
SLOTS_DECL_NEW = "One template with 2 slots, no gate."

# (id, role, description, [(old, new, expected_count)])
VARIANTS = [
    # AMENDMENT 2026-08-16 (council R1: terra-2 #25, sol-1 #33): "over the past
    # 100 days" could be read as excluding today / calendar days, so it was not
    # a PURE reorder; the placebo now uses the strict syntactic reorder.
    ("BL-00", "placebo", "paraphrase placebo: strict reorder of the modifiers, no content word added (amended 2026-08-16)",
     [(SMA, "its simple 100-day moving average", 2)]),
    ("BL-02a", "control", "contract-semantics control: delete cross bullet only",
     [(CROSS_BULLET, "", 1)]),
    ("BL-01a", "anchor", "type blanked (ANCHOR)",
     [(SMA, "its 100-day moving average", 2)]),
    ("BL-01b", "eligible", "period blanked",
     [(SMA, "its simple moving average", 2)]),
    ("BL-01c", "eligible", "type AND period blanked",
     [(SMA, "its moving average", 2)]),
    ("BL-02b'", "placebo", "FORM-CHANGE PLACEBO: full-information noun-event frame + cross bullet deleted",
     [(BUY_LINE, "Reason to buy: an upward cross of SPY's close through its 100-day simple moving average.", 1),
      (SELL_LINE, "Reason to sell: a downward cross of SPY's close through its 100-day simple moving average.", 1),
      (CROSS_BULLET, "", 1)]),
    ("BL-02b", "eligible", "operands dropped, direction kept + cross bullet deleted",
     [(BUY_LINE, "Reason to buy: an upward 100-day simple-moving-average cross on SPY.", 1),
      (SELL_LINE, "Reason to sell: a downward 100-day simple-moving-average cross on SPY.", 1),
      (CROSS_BULLET, "", 1)]),
    ("BL-02c", "eligible", "directionless: both reason clauses identical + cross bullet deleted",
     [(BUY_LINE, "Reason to buy: a 100-day simple-moving-average cross on SPY.", 1),
      (SELL_LINE, "Reason to sell: a 100-day simple-moving-average cross on SPY.", 1),
      (CROSS_BULLET, "", 1)]),
    ("BL-03", "eligible", "A size 40% -> unspecified percentage",
     [("invest 40% of total portfolio value in SPY", "invest a percentage of total portfolio value in SPY", 1)]),
    ("BL-04", "eligible", "red/green definition deleted (counting sentence stays)",
     [(RED_DEF, "", 1)]),
    ("BL-05", "eligible", "'3 consecutive days' -> 'a number of consecutive days'",
     [("has been red for 3 consecutive days", "has been red for a number of consecutive days", 1)]),
    ("BL-06", "eligible", "shortfall outcome blanked (two-span coupled edit; '$C if available' key stays bound)",
     [(B06_BODY_OLD, B06_BODY_NEW, 1),
      (B06_CON_OLD, B06_CON_NEW, 1)]),
    ("BL-07", "anchor", "RSI period blanked (ANCHOR)",
     [("AAPL's 14-day RSI closes above 60", "AAPL's RSI closes above 60", 1)]),
    ("BL-08", "eligible", "RSI threshold blanked",
     [("AAPL's 14-day RSI closes above 60", "AAPL's 14-day RSI closes above a threshold", 1)]),
    ("BL-09a", "eligible", "A sell details -> 'sell.' (contract untouched)",
     [("Sell details: liquidate Strategy A's entire lot.", "Sell details: sell.", 1)]),
    ("BL-09b", "eligible", "same body change + 'sell half' sentence deleted ('closed' sentence stays)",
     [("Sell details: liquidate Strategy A's entire lot.", "Sell details: sell.", 1),
      (SELL_HALF, "", 1)]),
    ("OM-A", "secondary", "missing-bar skip rule deleted (contract)",
     [(MISSING_BAR, "", 1)]),
    ("OM-B", "secondary", "private-lots / sells-before-buys bullet deleted",
     [(LOTS_BULLET, "", 1)]),
    ("OM-C", "secondary", "slot-independence declaration removed",
     [(SLOTS_DECL_OLD, SLOTS_DECL_NEW, 1)]),
    ("ER-01", "eligible-second-donor", "referent-ambiguity probe: A buys on 200-day cross up, sells 'when the SMA(50) crosses'",
     [(BUY_LINE, "Reason to buy: SPY's close crosses above its 200-day simple moving average.", 1),
      (SELL_LINE, "Reason to sell: when the SMA(50) crosses.", 1)]),
    # ER-01c: the owner-funded pinned control (2026-08-15) — a DERIVED edit
    # whose base is ER-01's text (5th tuple field), sell rule pinned to R1
    ("ER-01c", "control-second-donor", "ER-01 pinned control: sell rule pinned to R1 (close crosses below SMA(50))",
     [("Reason to sell: when the SMA(50) crosses.", "Reason to sell: SPY's close crosses below its 50-day simple moving average.", 1)],
     "ER-01"),
]


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def structural_asserts(vid, text):
    errs = []
    for i, line in enumerate(text.split("\n"), 1):
        if line.strip() in ("-", "- "):
            errs.append(f"line {i}: orphan list marker")
        if line.rstrip().endswith((";", ",")):
            errs.append(f"line {i}: dangling punctuation: {line.strip()[-40:]!r}")
    # defined-term bindings that must survive every variant that keeps the term
    if vid == "BL-06":
        if '"buy $C if available"' not in text or "if available." not in text:
            errs.append("BL-06: '$C if available' key not bound body<->contract")
    if vid == "BL-09b":
        if 'A lot is "closed" when it reaches zero shares.' not in text:
            errs.append("BL-09b: 'closed' sentence must stay")
        if "sell half" in text:
            errs.append("BL-09b: 'sell half' sentence not fully deleted")
    if vid == "BL-04":
        if '"Red for n consecutive days" is satisfied' not in text:
            errs.append("BL-04: counting sentence must stay")
    if vid == "ER-01":
        if CROSS_BULLET not in text:
            errs.append("ER-01: cross-definition clause must be KEPT")
    return errs


OUT.mkdir(parents=True, exist_ok=True)
records = []
texts = {}
ok = True
for item in VARIANTS:
    vid, role, desc, edits = item[:4]
    parent = item[4] if len(item) > 4 else None     # derived variants edit a PARENT's text
    text = texts[parent] if parent else BASE
    for old, new, expected in edits:
        found = text.count(old)
        if found != expected:
            print(f"FAIL {vid}: span occurs {found}x, expected {expected}: {old[:70]!r}")
            ok = False
            continue
        text = text.replace(old, new)
    errs = structural_asserts(vid, text)
    for e in errs:
        print(f"FAIL {vid}: {e}")
        ok = False
    texts[vid] = text
    records.append({
        "id": vid,
        "role": role,
        "description": desc,
        "edits": [{"old": o, "new": n, "count": c} for o, n, c in edits],
        "base": parent or "T1v0",
        "prompt": text,
        "sha256": sha(text),
        "chars_delta": len(text) - len(BASE),
    })
    if not errs:
        print(f"{vid}: OK  sha256={sha(text)[:16]}  delta={len(text)-len(BASE):+d}  base={parent or 'T1v0'}")

if not ok:
    sys.exit(1)

# cross-variant asserts
by_id = {r["id"]: r for r in records}
assert by_id["BL-02c"]["prompt"].count("a 100-day simple-moving-average cross on SPY.") == 2, "02c clauses not identical"
shas = [r["sha256"] for r in records]
assert len(set(shas)) == len(shas), "duplicate variant text"
eligible = [r["id"] for r in records if r["role"].startswith("eligible")]
assert len(eligible) == 12, f"eligible set != 12: {eligible}"
assert by_id["ER-01c"]["sha256"] == "ab9d7e0391d81213ab24e4dc727a615909b21cda7a4a163a6d575d9f68658bc6", "ER-01c sha drift"

# refuse to write if the existing frozen file holds ids this run would drop
_prev = OUT / "variants-v5.json"
if _prev.exists():
    _old = json.loads(_prev.read_text(encoding="utf-8"))["variants"]
    _dropped = {x["id"] for x in _old} - {r["id"] for r in records}
    if _dropped:
        print(f"REFUSING TO WRITE: would drop frozen ids {sorted(_dropped)}")
        sys.exit(2)
    AMENDED = {"BL-00": "2026-08-16 council R1 (terra-2 #25, sol-1 #33): strict reorder"}
    _changed = [x["id"] for x in _old if by_id.get(x["id"], {}).get("sha256") != x["sha256"] and x["id"] not in AMENDED]
    if _changed:
        print(f"REFUSING TO WRITE: frozen prompt text would change for {_changed} (a dated amendment is required)")
        sys.exit(3)

(OUT / "variants-v5.json").write_text(json.dumps({
    "generated": "2026-08-15",
    "pin": "PIN-v5-2026-08-15",
    "donor": "T1v0",
    "donor_sha256": sha(BASE),
    "count": len(records),
    "eligible_provisional": eligible,
    "variants": records,
}, indent=2), encoding="utf-8")
print(f"\nwrote {OUT / 'variants-v5.json'}  donor sha256={sha(BASE)[:16]}  n={len(records)}  eligible={len(eligible)}")
