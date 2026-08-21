# Data freeze record — PIN-v5 §4.6.4 (frozen BEFORE the oracle bank ran)

- **Window**: 2006-01-03 through 2015-12-31 inclusive (the donor's pinned
  backtest period; the window is not a researcher DOF — changing it
  post-lock requires re-running and re-hashing the ENTIRE bank with an
  Appendix A record).
- **Tickers**: SPY, AAPL, IBM, BAC, AIG — US equity DAILY resolution.
- **Vendor / provenance**: LEAN-shipped sample data in the Gate-2-verified
  workspace `complexity_axis_spike\lean_ws\data` (the same data every
  prior gate and corpus run used; physical path
  `Desktop\8.14\school\7.1 Research\...`, junction-cited as
  `Desktop\7.1 Research\...`).
- **Adjustment policy**: factor files present for all 5 tickers;
  normalization mode is the registered `input field` free DOF
  (adjusted = LEAN default reference level; raw = alternate level via
  SetDataNormalizationMode).
- **Engine build**: lean CLI 1.0.227, image per the Gate-2 recorded
  observation; runner timeout 600 s/backtest.

## Per-file SHA-256 (first 16 hex) and sizes

```
a6f609711a1f5502  equity\usa\daily\aapl.zip           104115
9e194e786d9104af  equity\usa\daily\aig.zip             93970
29224f2b8e9b03bd  equity\usa\daily\bac.zip             93290
dbc2eb8db4793506  equity\usa\daily\ibm.zip             97946
aaa1febad0cb8f91  equity\usa\daily\spy.zip            103363
86f7f2508a11259d  equity\usa\factor_files\aapl.csv      1304
1bd3b9e896fee271  equity\usa\factor_files\aig.csv       2328
2c6be614492df18b  equity\usa\factor_files\bac.csv       2614
8a310e86aca16430  equity\usa\factor_files\ibm.csv       2640
ad53e292de2e7076  equity\usa\factor_files\spy.csv       2649
e9def8800d5d5553  equity\usa\map_files\aapl.csv           32
697eb0d6b7c6fa11  equity\usa\map_files\aig.csv            30
a1ef20de5e24023c  equity\usa\map_files\bac.csv            43
e75919282b2c643b  equity\usa\map_files\ibm.csv            30
4765f330a156d4b0  equity\usa\map_files\spy.csv            30
```

**AGGREGATE sha256 (ordered file-hash concatenation):**
`5ae1bdb0e71af54f6c24c28a42bba431976348d40ca2a87ae9b75ec676094680`

The end-of-campaign oracle canary (§4.6.4) re-runs a registered oracle
subset against this same data and must reproduce bit-identical projected
tapes; a mismatch invalidates every code assigned since the last clean
canary and is reported, never patched.
