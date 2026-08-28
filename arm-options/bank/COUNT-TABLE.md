# O1 oracle-bank registration - derived count table

Derived by executing `bank_spec_o1.py:derived_table()` (validate_spec()
passes; every excluded-DOF set re-derives from the registered exclusion
arguments). The oracle bank is the ANSWER KEY: each run is one LEAN
backtest of the reference implementation at one parameter tuple.

| bank | resolutions | conditioning DOFs | runs |
|---|---:|---:|---:|
| DONOR | 1 | 0 | 32 |
| O1e1 | 5 | 2 | 215 |
| O1e2 | 5 | 2 | 215 |
| O1e3 | 2 | 3 | 284 |
| O1e4 | 5 | 3 | 335 |
| O1e5 | 5 | 3 | 335 |
| O1e6 | 5 | 1 | 135 |
| O1e7 | 5 | 2 | 215 |
| O1e8 | 5 | 1 | 135 |
| **TOTAL** | | | **1901** |

Registered windows: class separation 2023-07-01..2023-09-30;
donor full-window stability 2023-04-01..2026-06-30 (single run).
Ceiling: 2,500 runs; registered total sits 599 below it.

Provenance: specification authored in the Options-AI staging tree and
copied here verbatim 2026-08-28 so the study repo carries its own
registration; the bank build executes against this specification.
