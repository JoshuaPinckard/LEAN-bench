# LEAN Retrieval Datastore — Coder Spec (Roslyn path)

## Read this first

You are building a **frozen, reproducible documentation datastore** for a factorial
study on LLM trading-strategy generation. This datastore is a fixed instrument, not
a retrieval system to optimize.

Only two properties matter:
1. **Reproducible** — pinned inputs produce identical output forever.
2. **Not a confound** — retrieval returns relevant LEAN docs.

Do NOT optimize retrieval. Do NOT study retrieval. Build it, freeze it,
sanity-check it, never touch it again.

This spec has a **decision gate at Phase 2**. The build result selects the path.
Do not improvise around it.

---

## Phase 0 — Approach (already decided, do not re-litigate)

The datastore is the XML documentation the C# compiler emits from LEAN's `///`
doc-comments. Source-derived provenance:

```
LEAN @ pinned commit  →  dotnet build (project's own <DocumentationFile>)  →  XML docs
```

The C# compiler defines C#, so there is no parser-lag failure mode. This is why
this path is used instead of Doxygen. Doxygen, source-patching, and website
snapshotting were already evaluated and rejected. Do not revisit them.

---

## Phase 1 — Pinned inputs

- **Full clone** (NOT sparse): `https://github.com/QuantConnect/Lean`
- **Checkout commit:** `d2daf42d34a0c97225794e9b1afaef820434db69`
- **Install .NET 10 SDK** (LEAN targets `net10.0`). Pin the exact SDK version.
- Record commit + exact SDK version in `DATASTORE_SPEC` output **before building**.

---

## Phase 2 — DECISION GATE (do this before writing any parser)

Build:

```
dotnet build QuantConnect.Lean.sln -c Release
```

**Pass criterion — all three files exist after build:**
- `Algorithm/bin/Release/QuantConnect.Algorithm.xml`
- `Indicators/bin/Release/QuantConnect.Indicators.xml`
- `Common/bin/Release/QuantConnect.Common.xml`

**Branch — do not improvise:**

- **All three produced** → Roslyn verified. Continue to Phase 3.
- **Build fails after a genuine attempt** (real effort on dependency/SDK
  resolution — not a quick bail) → STOP. Switch to the Fallback (end of doc).
  Do NOT patch source. Do NOT try other Doxygen versions. Those are ruled out.

Report which branch occurred before proceeding.

---

## Phase 3 — Parse Roslyn XML to per-member chunks

**Note:** Roslyn XML format differs from Doxygen XML. Any earlier Doxygen parser
does NOT carry over. Roslyn emits flat entries:

```xml
<member name="M:QuantConnect.Algorithm.QCAlgorithm.SetHoldings(QuantConnect.Symbol,System.Decimal)">
  <summary>...</summary>
  <param name="symbol">...</param>
  <returns>...</returns>
</member>
```

Parser requirements:
- Iterate every `<member>` element.
- Parse the `name` ID: prefix `M:` = method, `P:` = property, `T:` = type.
  Recover class, member name, and parameter types from the ID string.
- One member = one chunk.
- Chunk text composition (keep identical to this):
  - Fully-qualified class name
  - Class summary (from the `T:` entry for that class)
  - Member name + signature reconstructed from the ID
  - Member `<summary>`
  - `<param>` names + descriptions
- Apply a defensive `MAX_CHARS` guard (e.g. 8000); document it as defensive-only.

**Re-measure the chunk count fresh.** Record it as the new canonical correctness
baseline. (Any chunk count from earlier Doxygen work does NOT apply here.)

---

## Phase 4 — Completeness check (Roslyn-specific, non-negotiable)

Roslyn only emits XML for members that HAVE a `///` comment. Undocumented members
are silently absent.

Do ONE of these and **state which in the spec output**:
- (a) Cross-check against public members from the compiled assemblies, OR
- (b) Explicitly scope the datastore to "documented members only" (defensible —
  identical to what a developer sees in the published API reference).

**Acceptance test:** confirm the `SetHoldings` overloads are present in the
chunk set. (This is the exact content that exposed the original gap.)

---

## Phase 5 — Embed once, pinned

- Open-weights model via `sentence-transformers`, run locally.
- **Pinned model:** `BAAI/bge-base-en-v1.5`. Pin the exact revision (HF commit
  hash) at first download. Never change it.
- Apply the model card's prescribed normalization / prefix convention.
  Read the card; do not assume generic cosine.
- Embed all chunks once → FAISS index. Hash the index.

---

## Phase 6 — Freeze + sanity check (the one non-negotiable check)

- Run ~10 hand-written LEAN queries, e.g.:
  - "how to warm up an indicator"
  - "set holdings to a percentage of portfolio"
  - "create an EMA on daily resolution"
- Eyeball that returned chunks are relevant LEAN members.
- This is a smoke test, NOT a retrieval evaluation. If sensible members come
  back, done. Never re-tune after this.

**Canonical artifact (record all in `DATASTORE_SPEC` output):**

```
source commit  +  .NET SDK version  +  embedding model revision  →  hashed FAISS index
```

---

## Phase 7 — Retrieval tool (for the agentic harness)

- Single function, one string argument.
- Returns top-k = **5** raw chunk texts (fixed; not tuned).
- Logs every query string + returned chunk IDs.

---

## OUT OF SCOPE — do not do

- Reranking
- Embedding-model comparison / bake-offs
- Chunking-strategy experiments
- Retrieval metric optimization (NDCG / recall studies)
- Patching LEAN source
- Trying alternate Doxygen versions

If you find yourself optimizing or studying retrieval, stop. It is not the study.

---

## FALLBACK (only if Phase 2 build fails after genuine effort)

Snapshot the published LEAN class reference instead of generating from source:

1. Crawl `https://www.lean.io/docs/v2/lean-engine/class-reference/` at a fixed
   date. Enumerate pages from the site's own class list + alphabetical member
   index pages (do not blind-spider). Store raw HTML. Hash the bundle.
2. Parse the uniform Doxygen-generated HTML: per class page extract class name,
   class brief, and each member's signature + summary + params. Same chunk
   composition as Phase 3. One member = one chunk.
3. **Completeness gate:** the alphabetical member-index pages list every
   documented member by design. Assert every indexed member resolved to a chunk.
   Confirm `SetHoldings` overloads present.
4. Phases 5–7 unchanged. Canonical artifact becomes:
   `reference URL + crawl date + raw-HTML bundle hash + embedding revision → hashed index`.

Use this ONLY with evidence that the build was intractable — not as a shortcut.
