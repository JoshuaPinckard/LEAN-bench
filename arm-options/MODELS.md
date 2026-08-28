# Pinned model matrix — options arm

Owner directive 2026-08-26: pin the models, and use what LEAN-Bench used —
"that's essentially all we have available." The pins below are taken from the
MEASURED lane inventory of the equity study (192 local lane files plus bare
cells and the audit ledger), not from memory.

## What the equity study actually used (measured)

| surface | model id (exact) | efforts used | where |
|---|---|---|---|
| codex CLI | `gpt-5.6-luna` | low, medium, high, xhigh, max | benchmark lanes |
| codex CLI | `gpt-5.6-terra` | low, medium, high, max | benchmark lanes |
| codex CLI | `gpt-5.6-sol` | low, medium | benchmark lanes (quota ordering: sol after luna/terra) |
| claude CLI | `claude-sonnet-5` | max | benchmark arm |
| bare (OpenAI API) | `gpt-5.6-luna` | — | H5 bare cells |
| bare (Anthropic via claude) | `claude-sonnet-5` | — | H5 bare cells |
| bare (Vertex) | `gemini-3.6-flash` | high | H5 bare cell |
| audit judges | `gpt-5.6-terra` (medium), `gemini-3.6-flash` (vertex), `claude-sonnet-5` | — | 400/400/400 panel |
| codex cloud | `cloud-default` (recorded as-is; overrides not verifiable in task records) | attempts 1/2/4/8/16 | cloud cells |

## Pins for the options arm

| lane | surface | model | effort | conditions | n |
|---|---|---|---|---|---|
| core 1 | codex | `gpt-5.6-luna` | low | base + noask | 30 eligible / 10 other |
| core 2 | codex | `gpt-5.6-terra` | low | base + noask | 30 eligible / 10 other |
| depth (after cores) | codex | `gpt-5.6-luna` | medium | base + noask | 30 eligible / 10 other |
| claude arm | claude | `claude-sonnet-5` | max | base + noask | 30 eligible / 10 other |
| gemini-family | vertex BARE | `gemini-3.6-flash` | high | base | 30 eligible / 10 other |

Rules:
- Exact ids only — never a bare alias ("luna"), never a newer model silently.
  A lane whose recorded `model` field differs from this table is quarantined,
  not graded.
- gemini-cli harness is DEAD (provider EOL, IneligibleTierError, 2026-08-24).
  The gemini-family leg is Vertex BARE only, labelled `bare_vertex_*` exactly
  as the equity H5 cell was — it is a bare surface, never presented as a
  harness cell. Antigravity probed 2026-08-26: no headless mode; documented,
  not used.
- Codex cloud arm cells, if run, record `cloud-default` and the attempts knob
  only — model/effort overrides are NOT verifiable in cloud task records
  (measured during the equity study) and are therefore never claimed.
- The audit uses its own frozen three-family panel and is untouched by this arm.

## Amendment 2026-08-28 - owner-directed expansion to equity parity

Owner directive (2026-08-28): "run the expanded version. do it in order though
so the things that can land immediately do and also the things that are not
important for sep9 can go at the end of the queue."

Queue order (draws; grading follows the same order after the oracle bank):
1. (running) sonnet-5 max - the registered core's open lane
2. (running) core top-offs: luna low, terra low, luna medium
3. parity codex lanes, serial, registered 30/20/10 targets, in this order
   (cheapest effort first, alternating models to spread quota):
   terra medium, luna high, terra high, luna xhigh, terra max, luna max,
   sol low, sol medium
4. bare cells: bare_openai gpt-5.6-luna high, bare_claude claude-sonnet-5 high
   (13 O1 prompts each, bare targets 30 eligible / 10 other)
5. cloud attempts ladder (cloud-default; attempts 1/2/4/8/16) - LAST; queued,
   launched manually with the routing-trap checklist from the equity study.

Registered targets for every lane: eligible 30 per condition, anchors 20,
donor/pins 10. luna_medium's 60-per-eligible overdraw (earlier wrong resume
target) is kept as extra data; completion is judged against this registration.
