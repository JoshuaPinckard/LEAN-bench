<script setup>
import { ref, watch, computed } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  callId: { type: String, default: null },
})
defineEmits(['close'])

const tab = ref('transcript')
const data = ref(null)
const error = ref(null)
const loading = ref(false)

// Per-turn expansion state. Keys are turn_index (number). Default-collapsed
// so a 24-turn cell starts as a glanceable list of one-liners.
const expandedTurns = ref(new Set())
// Within an expanded turn, separate accordions for the heavy text blocks.
const turnSubExpand = ref({})  // { [turn_index]: { userMsg, response, rag, compiler, judgeA, judgeB } }

// Top-level (non-per-turn) expansion state.
const showSystemPrompt = ref(false)
const showAllTurnsTable = ref(false)

// Pipeline-tab expansion state.
const expandedStage = ref(new Set())

// Eval-tab expansion state.
const evalSections = ref({
  identity: true,
  stages: true,
  metrics: false,
  cost: false,
  errors: true,
})

async function load(id) {
  data.value = null
  error.value = null
  expandedTurns.value = new Set()
  turnSubExpand.value = {}
  expandedStage.value = new Set()
  showSystemPrompt.value = false
  showAllTurnsTable.value = false
  if (!id) return
  loading.value = true
  try {
    data.value = await api.getCall(id)
    tab.value = 'transcript'
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

watch(() => props.callId, load, { immediate: true })

function copy(text) {
  navigator.clipboard.writeText(text || '').catch(() => {})
}

function toggleTurn(i) {
  const s = new Set(expandedTurns.value)
  if (s.has(i)) s.delete(i); else s.add(i)
  expandedTurns.value = s
  if (!turnSubExpand.value[i]) {
    // First open: pre-expand the model response + compiler output so the
    // reviewer doesn't have to chase two more clicks.
    turnSubExpand.value = {
      ...turnSubExpand.value,
      [i]: { userMsg: false, response: true, rag: true, compiler: true, judgeA: false, judgeB: false, schema: true },
    }
  }
}
function expandAllTurns() {
  if (!turns.value) return
  expandedTurns.value = new Set(turns.value.map(t => t.turn_index))
  const next = { ...turnSubExpand.value }
  for (const t of turns.value) {
    if (!next[t.turn_index]) {
      next[t.turn_index] = { userMsg: false, response: true, rag: true, compiler: true, judgeA: false, judgeB: false, schema: true }
    }
  }
  turnSubExpand.value = next
}
function collapseAllTurns() {
  expandedTurns.value = new Set()
}
function toggleSub(turnIdx, key) {
  const cur = turnSubExpand.value[turnIdx] || {}
  turnSubExpand.value = {
    ...turnSubExpand.value,
    [turnIdx]: { ...cur, [key]: !cur[key] },
  }
}
function isSub(turnIdx, key) {
  return !!(turnSubExpand.value[turnIdx] || {})[key]
}

function toggleStage(stage) {
  const s = new Set(expandedStage.value)
  if (s.has(stage)) s.delete(stage); else s.add(stage)
  expandedStage.value = s
}

function toggleEval(section) {
  evalSections.value = { ...evalSections.value, [section]: !evalSections.value[section] }
}

// ---- computed slices ----------------------------------------------------

const transcript = computed(() => data.value?.transcript || null)
const turns = computed(() => data.value?.turns || [])
const finalTurn = computed(() => transcript.value?.final_turn || null)
const finalCode = computed(() => {
  if (finalTurn.value?.response_code_extracted) return finalTurn.value.response_code_extracted
  return data.value?.generated_code || null
})

// Turn classification by inspecting tool_events. Each turn has exactly one
// "kind" (rag | code | invalid) — derive a single tag for the row badge.
function turnKind(t) {
  const evs = t.tool_events || []
  if (evs.find(e => e.name === 'rag_retrieve' || e.name === 'qc_docs_retrieve')) return 'rag'
  if (evs.find(e => e.name === 'code_attempt')) return 'code'
  if (evs.find(e => e.name === 'invalid_response')) return 'invalid'
  return 'unknown'
}

// Find the first event of a given name on a turn (events are unique per turn).
function findEvent(t, name) {
  return (t.tool_events || []).find(e => e.name === name) || null
}

// Stage-results object for a code-attempt turn (may be null on RAG/invalid).
function stageResults(t) {
  const code = findEvent(t, 'code_attempt')
  return code?.stage_results || null
}

// Compact stage badge string, e.g. "C✓ R✓ T✗" for a turn that compiled and
// ran but placed no trades. Renders inline next to the turn header.
function stageBadges(t) {
  const sr = stageResults(t)
  if (!sr) return null
  const out = []
  for (const [key, label] of [
    ['compile_pass', 'C'], ['runtime_pass', 'R'], ['trade_pass', 'T'],
    ['schema_pass', 'S'], ['judge_pass', 'J'],
  ]) {
    const v = sr[key]
    out.push({ label, state: v === true ? 'pass' : v === false ? 'fail' : 'skip' })
  }
  return out
}

// First-fail stage for the turn header.
function firstFailLabel(t) {
  const code = findEvent(t, 'code_attempt')
  return code?.first_fail || null
}

// Compiler log: a one-line "highlight" for the row header. Falls back to
// the trailer (LEAN_RUN_FINISHED / ORDERS_PLACED:N) when no ERROR:: present.
function logHighlight(tail) {
  if (!tail) return ''
  const lines = tail.split(/\r?\n/).filter(Boolean)
  for (let i = lines.length - 1; i >= 0; i--) {
    if (/ERROR::/i.test(lines[i])) return lines[i].trim()
  }
  for (let i = lines.length - 1; i >= 0; i--) {
    const ln = lines[i].trim()
    if (/^(LEAN_RUN_FINISHED|TIMEOUT_EXCEEDED|INFRASTRUCTURE_ERROR|ORDERS_PLACED:)/.test(ln)) {
      return ln
    }
  }
  return lines[lines.length - 1].slice(0, 160)
}

function turnTitle(t) {
  const kind = turnKind(t)
  if (kind === 'rag') {
    const ev = findEvent(t, 'rag_retrieve') || findEvent(t, 'qc_docs_retrieve')
    return `RAG · ${ev?.query || '(empty query)'}`
  }
  if (kind === 'code') {
    const code = findEvent(t, 'code_attempt')
    const bt = findEvent(t, 'lean_backtest')
    const ff = code?.first_fail
    if (ff) return `Code · ${code.code_chars} chars · failed at ${ff}`
    if (code?.stage_results && Object.values(code.stage_results).every(v => v === true)) {
      return `Code · ${code.code_chars} chars · ALL GATES PASSED`
    }
    return `Code · ${code?.code_chars || 0} chars · ${logHighlight(bt?.log_tail) || 'no log'}`
  }
  if (kind === 'invalid') {
    const ev = findEvent(t, 'invalid_response')
    return `Invalid · ${ev?.reason || 'unparseable response'}`
  }
  return '(unrecognised turn)'
}

function exitBadge(status) {
  if (status === 'completed')    return { cls: 'pass',    label: 'completed' }
  if (status === 'timeout')      return { cls: 'fail',    label: 'timeout' }
  if (status === 'docker_error') return { cls: 'fail',    label: 'docker_error' }
  if (status === 'infra_error')  return { cls: 'fail',    label: 'infra_error' }
  return { cls: 'pending', label: status || '—' }
}

// ---- pipeline tab -------------------------------------------------------

const PIPELINE_STAGES = [
  { key: 'compile', label: '1. Compile (AST)',   description: 'Python AST parse. Fast pre-gate before LEAN runs.' },
  { key: 'runtime', label: '2. Runtime (LEAN)',  description: 'lean_backtest_tool reports LEAN_RUN_FINISHED with no ERROR:: lines.' },
  { key: 'trade',   label: '3. Trade activity',  description: 'At least one order placed in the backtest window.' },
  { key: 'schema',  label: '4. Schema check',    description: 'Mechanical adherence to curator-pinned start/end/securities/resolution. Hidden gate.' },
  { key: 'judge',   label: '5. Dual judge',      description: 'Average of two LLM judges >= JUDGE_PASS_THRESHOLD. Hidden gate.' },
]

function stageState(stageKey) {
  const c = data.value
  if (!c) return 'unknown'
  const fp = transcript.value?.first_pass || {}
  const passedAt = fp[stageKey]
  if (passedAt != null) return 'passed'
  // Was it tried at all? Look at the latest code attempt's stage_results.
  const code = (transcript.value?.code_events || []).slice(-1)[0]
  const sr = code?.stage_results || {}
  const key = stageKey + '_pass'
  if (sr[key] === false) return 'failed'
  if (sr[key] === null || sr[key] === undefined) return 'skipped'
  return 'unknown'
}

function stageBadgeClass(state) {
  if (state === 'passed')  return 'pass'
  if (state === 'failed')  return 'fail'
  if (state === 'skipped') return 'pending'
  return 'pending'
}
function stageBadgeLabel(state) {
  if (state === 'passed')  return 'PASS'
  if (state === 'failed')  return 'FAIL'
  if (state === 'skipped') return 'SKIPPED'
  return '—'
}

// For each stage, the per-turn pass/fail history (for the matrix view).
function stageHistory(stageKey) {
  const key = stageKey + '_pass'
  return (transcript.value?.code_events || []).map(ev => ({
    turn_index: ev.turn_index,
    value:      (ev.stage_results || {})[key],
  }))
}

const latestSchemaEvent = computed(() => {
  const list = transcript.value?.schema_events || []
  return list[list.length - 1] || null
})
const latestJudgeEvent = computed(() => {
  const list = transcript.value?.judge_events || []
  return list[list.length - 1] || null
})
</script>

<template>
  <div v-if="callId" class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal">
      <div class="modal-header">
        <h2 v-if="data">
          {{ data.model_id }}
          · {{ data.condition_id }}
          · trial {{ data.trial_index }}
          <span class="mono header-id">{{ data.call_id }}</span>
        </h2>
        <h2 v-else>Loading…</h2>
        <button class="icon" @click="$emit('close')" style="font-size: 18px;">✕</button>
      </div>

      <div class="modal-tabs" v-if="data">
        <button class="tab" :class="{ active: tab === 'transcript' }" @click="tab = 'transcript'">
          Transcript
          <span v-if="transcript" class="tab-sub mono">
            <template v-if="data.tool_agentic_loop">
              {{ transcript.total_turns }}t · {{ transcript.rag_count }} rag · {{ transcript.code_count }} code · {{ transcript.invalid_count }} inv
            </template>
            <template v-else>one-shot</template>
          </span>
        </button>
        <button class="tab" :class="{ active: tab === 'pipeline' }" @click="tab = 'pipeline'">
          Pipeline
          <span v-if="transcript" class="tab-sub mono">
            {{ Object.values(transcript.first_pass || {}).filter(v => v != null).length }} / 5 gates
          </span>
        </button>
        <button class="tab" :class="{ active: tab === 'code' }" @click="tab = 'code'">Final code</button>
        <button class="tab" :class="{ active: tab === 'eval' }" @click="tab = 'eval'">Evaluation</button>
        <button class="tab" :class="{ active: tab === 'raw' }" @click="tab = 'raw'">Raw</button>
      </div>

      <div class="modal-body">
        <div v-if="loading"><span class="spinner"></span> Loading…</div>
        <div v-else-if="error" class="error-box">{{ error }}</div>

        <template v-else-if="data">
          <!-- ============================================================ -->
          <!-- TRANSCRIPT TAB                                                -->
          <!-- ============================================================ -->
          <div v-if="tab === 'transcript'" class="transcript">
            <template v-if="transcript">
              <!-- Summary strip -->
              <div class="strip">
                <div class="strip-item">
                  <div class="strip-label">Turns used</div>
                  <div class="strip-value">{{ transcript.total_turns }} / {{ data.max_turns_allowed }}</div>
                </div>
                <div class="strip-item">
                  <div class="strip-label">RAG queries</div>
                  <div class="strip-value">{{ transcript.rag_count }}</div>
                </div>
                <div class="strip-item">
                  <div class="strip-label">Code attempts</div>
                  <div class="strip-value">{{ transcript.code_count }}</div>
                </div>
                <div class="strip-item">
                  <div class="strip-label">Invalid replies</div>
                  <div class="strip-value">{{ transcript.invalid_count }}</div>
                </div>
                <div class="strip-item">
                  <div class="strip-label">Final code at</div>
                  <div class="strip-value">
                    {{ transcript.final_turn_index != null ? 'turn ' + (transcript.final_turn_index + 1) : '—' }}
                  </div>
                </div>
                <div class="strip-item">
                  <div class="strip-label">Overall</div>
                  <div class="strip-value">
                    <span class="stage-pill" :class="data.overall_pass === true ? 'pass' : data.overall_pass === false ? 'fail' : 'pending'">
                      {{ data.overall_pass === true ? 'PASS' : data.overall_pass === false ? 'FAIL' : '—' }}
                    </span>
                  </div>
                </div>
              </div>

              <!-- System prompt collapsed by default -->
              <section class="section">
                <div class="card" :class="{ open: showSystemPrompt }">
                  <button class="card-head" @click="showSystemPrompt = !showSystemPrompt">
                    <span class="tag">SYSTEM</span>
                    <span class="card-title">
                      System prompt
                      <span class="muted">(sha {{ (data.system_prompt_sha || '').slice(0, 8) || '—' }})</span>
                    </span>
                    <span class="chev">{{ showSystemPrompt ? '▾' : '▸' }}</span>
                  </button>
                  <div v-if="showSystemPrompt" class="card-body">
                    <pre class="code-block code-light"><code>{{ transcript.system_prompt || '(unavailable)' }}</code></pre>
                  </div>
                </div>
              </section>

              <!-- Per-turn drill-down -->
              <section class="section" v-if="turns.length">
                <div class="section-header">
                  <h3 class="section-title">Per-turn drill-down ({{ turns.length }})</h3>
                  <div class="section-actions">
                    <button class="secondary tiny" @click="expandAllTurns">Expand all</button>
                    <button class="secondary tiny" @click="collapseAllTurns">Collapse all</button>
                  </div>
                </div>
                <p class="muted-small">
                  Each turn is one provider call. Click the row to expand the
                  user message, model response, RAG result, compiler log,
                  schema violations, and per-judge reasoning.
                </p>

                <div class="cards">
                  <div v-for="t in turns" :key="t.turn_id"
                       class="card turn-card" :class="{ open: expandedTurns.has(t.turn_index), 'is-final': t.is_final_turn }">
                    <button class="card-head turn-head" @click="toggleTurn(t.turn_index)">
                      <span class="tag turn-tag">T{{ t.turn_index + 1 }}</span>
                      <span class="tag" :class="'kind-' + turnKind(t)">{{ turnKind(t).toUpperCase() }}</span>
                      <span class="card-title turn-title">{{ turnTitle(t) }}</span>
                      <span v-if="stageBadges(t)" class="stage-badges">
                        <span v-for="b in stageBadges(t)" :key="b.label"
                              class="stage-mini" :class="b.state" :title="b.label">{{ b.label }}</span>
                      </span>
                      <span v-if="t.is_final_turn" class="tag final-tag">FINAL</span>
                      <span class="muted small mono">{{ t.response_tokens_in }}/{{ t.response_tokens_out }} tok · {{ t.wall_clock_seconds?.toFixed(1) }}s</span>
                      <span class="chev">{{ expandedTurns.has(t.turn_index) ? '▾' : '▸' }}</span>
                    </button>

                    <div v-if="expandedTurns.has(t.turn_index)" class="card-body turn-body">

                      <!-- Sub-section: user message sent on this turn -->
                      <div class="sub">
                        <button class="sub-head" @click="toggleSub(t.turn_index, 'userMsg')">
                          <span class="chev">{{ isSub(t.turn_index, 'userMsg') ? '▾' : '▸' }}</span>
                          <span class="sub-title">User message sent this turn</span>
                          <span class="muted small">({{ (t.user_message || '').length }} chars)</span>
                        </button>
                        <div v-if="isSub(t.turn_index, 'userMsg')" class="sub-body">
                          <button class="secondary tiny" @click="copy(t.user_message)">Copy</button>
                          <pre class="code-block code-light"><code>{{ t.user_message || '(not recorded)' }}</code></pre>
                        </div>
                      </div>

                      <!-- Sub-section: model response -->
                      <div class="sub">
                        <button class="sub-head" @click="toggleSub(t.turn_index, 'response')">
                          <span class="chev">{{ isSub(t.turn_index, 'response') ? '▾' : '▸' }}</span>
                          <span class="sub-title">Model response</span>
                          <span class="muted small">({{ (t.response_text || '').length }} chars)</span>
                        </button>
                        <div v-if="isSub(t.turn_index, 'response')" class="sub-body">
                          <button class="secondary tiny" @click="copy(t.response_text)">Copy</button>
                          <pre class="code-block"><code>{{ t.response_text || '(empty response)' }}</code></pre>
                        </div>
                      </div>

                      <!-- Sub-section: RAG result (only for rag turns) -->
                      <template v-if="findEvent(t, 'rag_retrieve') || findEvent(t, 'qc_docs_retrieve')">
                        <div class="sub">
                          <button class="sub-head" @click="toggleSub(t.turn_index, 'rag')">
                            <span class="chev">{{ isSub(t.turn_index, 'rag') ? '▾' : '▸' }}</span>
                            <span class="sub-title">RAG result</span>
                            <span class="muted small">({{ (findEvent(t, 'rag_retrieve') || findEvent(t, 'qc_docs_retrieve')).output_len }} chars)</span>
                          </button>
                          <div v-if="isSub(t.turn_index, 'rag')" class="sub-body">
                            <div class="muted small" style="margin-bottom: 4px;">
                              Query:
                              <code>{{ (findEvent(t, 'rag_retrieve') || findEvent(t, 'qc_docs_retrieve')).query || '(empty)' }}</code>
                            </div>
                            <pre class="code-block code-light"><code>{{ (findEvent(t, 'rag_retrieve') || findEvent(t, 'qc_docs_retrieve')).output_preview }}</code></pre>
                          </div>
                        </div>
                      </template>

                      <!-- Sub-section: compiler log (lean_backtest event) -->
                      <template v-if="findEvent(t, 'lean_backtest')">
                        <div class="sub">
                          <button class="sub-head" @click="toggleSub(t.turn_index, 'compiler')">
                            <span class="chev">{{ isSub(t.turn_index, 'compiler') ? '▾' : '▸' }}</span>
                            <span class="sub-title">Compiler output</span>
                            <span class="stage-pill tiny" :class="exitBadge(findEvent(t, 'lean_backtest').exit_status).cls">
                              {{ exitBadge(findEvent(t, 'lean_backtest').exit_status).label }}
                            </span>
                            <span v-if="findEvent(t, 'lean_backtest').feedback_shown_to_model" class="tag visible-tag" title="C3/C4: output was injected into the next turn's context history">
                              shown to model
                            </span>
                            <span v-else class="tag hidden-tag" title="C1/C2: gate-only — output not shown to the model">
                              gate-only
                            </span>
                            <span class="muted small">({{ findEvent(t, 'lean_backtest').output_len }} chars)</span>
                          </button>
                          <div v-if="isSub(t.turn_index, 'compiler')" class="sub-body">
                            <pre class="code-block code-dark"><code>{{ findEvent(t, 'lean_backtest').log_tail || '(empty log)' }}</code></pre>
                          </div>
                        </div>
                      </template>

                      <!-- Sub-section: schema check (always hidden gate; surfaced here for diagnostics) -->
                      <template v-if="findEvent(t, 'schema_check')">
                        <div class="sub">
                          <button class="sub-head" @click="toggleSub(t.turn_index, 'schema')">
                            <span class="chev">{{ isSub(t.turn_index, 'schema') ? '▾' : '▸' }}</span>
                            <span class="sub-title">Schema check</span>
                            <span class="stage-pill tiny" :class="findEvent(t, 'schema_check').schema_pass === true ? 'pass' : 'fail'">
                              {{ findEvent(t, 'schema_check').schema_pass === true ? 'pass' : 'fail' }}
                            </span>
                            <span class="tag hidden-tag" title="Hidden gate — never visible to the model">hidden gate</span>
                            <span class="muted small">
                              ({{ (findEvent(t, 'schema_check').violations || []).length }} violations)
                            </span>
                          </button>
                          <div v-if="isSub(t.turn_index, 'schema')" class="sub-body">
                            <ul v-if="(findEvent(t, 'schema_check').violations || []).length" class="violations">
                              <li v-for="(v, i) in findEvent(t, 'schema_check').violations" :key="i">
                                <code>{{ v }}</code>
                              </li>
                            </ul>
                            <div v-else class="muted">No violations on this turn.</div>
                          </div>
                        </div>
                      </template>

                      <!-- Sub-section: judge A reasoning -->
                      <template v-if="findEvent(t, 'judge')">
                        <div class="sub">
                          <button class="sub-head" @click="toggleSub(t.turn_index, 'judgeA')">
                            <span class="chev">{{ isSub(t.turn_index, 'judgeA') ? '▾' : '▸' }}</span>
                            <span class="sub-title">Judge A (claude-sonnet)</span>
                            <span class="muted small mono">
                              score {{ findEvent(t, 'judge').judge_score_a != null ? findEvent(t, 'judge').judge_score_a.toFixed(3) : '—' }}
                            </span>
                            <span class="tag hidden-tag" title="Hidden gate — never visible to the model">hidden gate</span>
                          </button>
                          <div v-if="isSub(t.turn_index, 'judgeA')" class="sub-body">
                            <pre class="code-block code-light"><code>{{ findEvent(t, 'judge').judge_reasoning_a || '(no reasoning)' }}</code></pre>
                          </div>
                        </div>
                        <div class="sub">
                          <button class="sub-head" @click="toggleSub(t.turn_index, 'judgeB')">
                            <span class="chev">{{ isSub(t.turn_index, 'judgeB') ? '▾' : '▸' }}</span>
                            <span class="sub-title">Judge B (gpt-5.4)</span>
                            <span class="muted small mono">
                              score {{ findEvent(t, 'judge').judge_score_b != null ? findEvent(t, 'judge').judge_score_b.toFixed(3) : '—' }}
                            </span>
                            <span class="tag hidden-tag">hidden gate</span>
                          </button>
                          <div v-if="isSub(t.turn_index, 'judgeB')" class="sub-body">
                            <pre class="code-block code-light"><code>{{ findEvent(t, 'judge').judge_reasoning_b || '(no reasoning)' }}</code></pre>
                          </div>
                        </div>
                      </template>

                    </div>
                  </div>
                </div>
              </section>

              <!-- Final code -->
              <section class="section" v-if="finalCode">
                <h3 class="section-title">Final extracted code</h3>
                <div class="section-actions" style="margin-bottom: 6px;">
                  <button class="secondary tiny" @click="copy(finalCode)">Copy</button>
                </div>
                <pre class="code-block"><code>{{ finalCode }}</code></pre>
              </section>

            </template>
          </div>

          <!-- ============================================================ -->
          <!-- PIPELINE TAB                                                  -->
          <!-- ============================================================ -->
          <div v-if="tab === 'pipeline'" class="pipeline">
            <p class="muted-small">
              Pipeline gates run in order — each gate is skipped when the
              prior gate failed. The number shown for "first passed" is the
              turn (1-indexed) on which that gate first reported success.
            </p>

            <div class="cards">
              <div v-for="stage in PIPELINE_STAGES" :key="stage.key"
                   class="card stage-card" :class="{ open: expandedStage.has(stage.key) }">
                <button class="card-head" @click="toggleStage(stage.key)">
                  <span class="tag mono stage-num">{{ stage.label }}</span>
                  <span class="card-title">{{ stage.description }}</span>
                  <span class="stage-pill" :class="stageBadgeClass(stageState(stage.key))">
                    {{ stageBadgeLabel(stageState(stage.key)) }}
                  </span>
                  <span class="muted small mono" v-if="(transcript?.first_pass || {})[stage.key] != null">
                    first passed @ turn {{ (transcript.first_pass[stage.key] || 0) + 1 }}
                  </span>
                  <span class="chev">{{ expandedStage.has(stage.key) ? '▾' : '▸' }}</span>
                </button>
                <div v-if="expandedStage.has(stage.key)" class="card-body">

                  <!-- Per-turn matrix for this stage -->
                  <div class="stage-history">
                    <span class="muted small">Per-code-attempt outcome:</span>
                    <div class="matrix-row">
                      <div v-for="h in stageHistory(stage.key)" :key="h.turn_index"
                           class="matrix-cell"
                           :class="h.value === true ? 'pass' : h.value === false ? 'fail' : 'skip'"
                           :title="'turn ' + (h.turn_index + 1)">
                        <span class="matrix-turn">T{{ h.turn_index + 1 }}</span>
                        <span class="matrix-mark">
                          {{ h.value === true ? '✓' : h.value === false ? '✗' : '—' }}
                        </span>
                      </div>
                      <span v-if="!stageHistory(stage.key).length" class="muted">No code attempts.</span>
                    </div>
                  </div>

                  <!-- Stage-specific drilldown -->
                  <div v-if="stage.key === 'schema' && latestSchemaEvent" style="margin-top: 10px;">
                    <div class="muted small">Latest schema check (turn {{ latestSchemaEvent.turn_index + 1 }}):</div>
                    <ul v-if="(latestSchemaEvent.violations || []).length" class="violations">
                      <li v-for="(v, i) in latestSchemaEvent.violations" :key="i">
                        <code>{{ v }}</code>
                      </li>
                    </ul>
                    <div v-else class="muted">No violations on the latest schema run.</div>
                  </div>

                  <div v-if="stage.key === 'judge' && latestJudgeEvent" style="margin-top: 10px;">
                    <div class="muted small" style="margin-bottom: 4px;">
                      Latest judge run (turn {{ latestJudgeEvent.turn_index + 1 }})
                      ·
                      <span class="mono">avg {{ latestJudgeEvent.judge_score != null ? latestJudgeEvent.judge_score.toFixed(3) : '—' }}</span>
                      ·
                      <span class="mono">A {{ latestJudgeEvent.judge_score_a != null ? latestJudgeEvent.judge_score_a.toFixed(3) : '—' }}</span>
                      /
                      <span class="mono">B {{ latestJudgeEvent.judge_score_b != null ? latestJudgeEvent.judge_score_b.toFixed(3) : '—' }}</span>
                      · threshold ≥ {{ data.judge_threshold ?? '—' }}
                    </div>
                    <div v-if="latestJudgeEvent.judge_error" class="error-box">
                      Judge error: {{ latestJudgeEvent.judge_error }}
                    </div>
                    <details>
                      <summary>Judge A reasoning</summary>
                      <pre class="code-block code-light"><code>{{ latestJudgeEvent.judge_reasoning_a || '(none)' }}</code></pre>
                    </details>
                    <details>
                      <summary>Judge B reasoning</summary>
                      <pre class="code-block code-light"><code>{{ latestJudgeEvent.judge_reasoning_b || '(none)' }}</code></pre>
                    </details>
                  </div>

                  <div v-if="stage.key === 'compile'" class="muted small" style="margin-top: 8px;">
                    Compile here = Python <code>ast.parse()</code> on the
                    extracted code fence. LEAN's own import-time errors are
                    reported under "Runtime" (they appear in the
                    <code>lean_backtest_tool</code> output as ERROR:: lines).
                  </div>

                  <div v-if="stage.key === 'runtime'" class="muted small" style="margin-top: 8px;">
                    Runtime passes when <code>LEAN_RUN_FINISHED</code> is in
                    the trailer AND no <code>ERROR::</code> lines are present
                    in the filtered log. Source: lean_backtest_tool.
                  </div>

                  <div v-if="stage.key === 'trade'" class="muted small" style="margin-top: 8px;">
                    Parsed from the <code>ORDERS_PLACED: &lt;n&gt;</code>
                    trailer line. Pass when n ≥ 1. <code>num_trades = unknown</code>
                    is treated as skipped.
                  </div>

                </div>
              </div>
            </div>
          </div>

          <!-- ============================================================ -->
          <!-- CODE TAB                                                      -->
          <!-- ============================================================ -->
          <div v-if="tab === 'code'">
            <button class="secondary tiny" style="margin-bottom: 8px;" @click="copy(finalCode)">
              Copy
            </button>
            <pre class="code-block"><code>{{ finalCode || '(no code extracted)' }}</code></pre>
          </div>

          <!-- ============================================================ -->
          <!-- EVALUATION TAB                                                -->
          <!-- ============================================================ -->
          <div v-if="tab === 'eval'" class="eval">
            <div v-if="data.status === 'excluded'" class="error-box excluded-box">
              <strong>Excluded by design.</strong>
              Reason: <code>{{ data.excluded_reason || 'unspecified' }}</code>.
              No provider, backtest, or judge call was made.
            </div>

            <!-- ERRORS SECTION (only shows when there are errors) -->
            <section v-if="data.error || data.judge_error" class="card" :class="{ open: evalSections.errors }">
              <button class="card-head" @click="toggleEval('errors')">
                <span class="tag fail-tag">ERRORS</span>
                <span class="card-title">Errors recorded against this call</span>
                <span class="chev">{{ evalSections.errors ? '▾' : '▸' }}</span>
              </button>
              <div v-if="evalSections.errors" class="card-body">
                <div v-if="data.error" class="error-box">
                  <strong>Cell error:</strong> {{ data.error }}
                </div>
                <div v-if="data.judge_error" class="error-box" style="margin-top: 8px;">
                  <strong>Judge error:</strong> {{ data.judge_error }}
                </div>
              </div>
            </section>

            <!-- IDENTITY / PROVENANCE -->
            <section class="card" :class="{ open: evalSections.identity }">
              <button class="card-head" @click="toggleEval('identity')">
                <span class="tag">IDENTITY</span>
                <span class="card-title">Identity & provenance</span>
                <span class="chev">{{ evalSections.identity ? '▾' : '▸' }}</span>
              </button>
              <div v-if="evalSections.identity" class="card-body">
                <table class="data">
                  <tbody>
                    <tr><th>status</th><td><span class="stage-pill" :class="data.status === 'completed' ? 'pass' : data.status === 'error' ? 'fail' : 'pending'">{{ data.status || '—' }}</span></td></tr>
                    <tr><th>condition</th><td><code>{{ data.condition_id }}</code></td></tr>
                    <tr><th>model</th><td><code>{{ data.model_id }}</code> <span class="muted small">({{ data.model_version }})</span></td></tr>
                    <tr><th>trial</th><td>{{ data.trial_index }}</td></tr>
                    <tr><th>benchmark_version</th><td><code>{{ data.benchmark_version || '—' }}</code></td></tr>
                    <tr><th>prompt_set_sha256</th><td><code class="small mono">{{ (data.prompt_set_sha256 || '').slice(0, 16) || '—' }}…</code></td></tr>
                    <tr><th>system_prompt_sha</th><td><code class="small mono">{{ (data.system_prompt_sha || '').slice(0, 16) || '—' }}…</code></td></tr>
                    <tr><th>judge_version</th><td><code>{{ data.judge_version || '—' }}</code></td></tr>
                    <tr><th>judge_threshold</th><td><code>≥ {{ data.judge_threshold ?? '—' }}</code></td></tr>
                    <tr><th>artifact_sha256</th><td><code class="small mono">{{ (data.artifact_sha256 || '').slice(0, 24) || '—' }}…</code></td></tr>
                  </tbody>
                </table>
              </div>
            </section>

            <!-- PIPELINE STAGES -->
            <section class="card" :class="{ open: evalSections.stages }">
              <button class="card-head" @click="toggleEval('stages')">
                <span class="tag">STAGES</span>
                <span class="card-title">5-stage pipeline outcomes</span>
                <span class="chev">{{ evalSections.stages ? '▾' : '▸' }}</span>
              </button>
              <div v-if="evalSections.stages" class="card-body">
                <table class="data">
                  <thead>
                    <tr>
                      <th>Stage</th>
                      <th>Result</th>
                      <th>First passed at turn</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>1. Compile (AST)</td>
                      <td><span class="stage-pill" :class="data.compile_pass === true ? 'pass' : data.compile_pass === false ? 'fail' : 'pending'">{{ data.compile_pass === null ? '—' : data.compile_pass ? 'pass' : 'fail' }}</span></td>
                      <td class="mono">{{ data.first_pass_compile != null ? data.first_pass_compile + 1 : '—' }}</td>
                    </tr>
                    <tr>
                      <td>2. Runtime (LEAN)</td>
                      <td><span class="stage-pill" :class="data.backtest_pass === true ? 'pass' : data.backtest_pass === false ? 'fail' : 'pending'">{{ data.backtest_pass === null ? '—' : data.backtest_pass ? 'pass' : 'fail' }}</span></td>
                      <td class="mono">{{ data.first_pass_runtime != null ? data.first_pass_runtime + 1 : '—' }}</td>
                    </tr>
                    <tr>
                      <td>3. Trade activity</td>
                      <td><span class="stage-pill" :class="data.trade_pass === true ? 'pass' : data.trade_pass === false ? 'fail' : 'pending'">{{ data.trade_pass === null ? '—' : data.trade_pass ? 'pass' : 'fail' }}</span></td>
                      <td class="mono">{{ data.first_pass_trade != null ? data.first_pass_trade + 1 : '—' }}</td>
                    </tr>
                    <tr>
                      <td>4. Schema check <span class="muted small">(hidden)</span></td>
                      <td><span class="stage-pill" :class="data.schema_pass === true ? 'pass' : data.schema_pass === false ? 'fail' : 'pending'">{{ data.schema_pass === null ? '—' : data.schema_pass ? 'pass' : 'fail' }}</span></td>
                      <td class="mono">{{ data.first_pass_schema != null ? data.first_pass_schema + 1 : '—' }}</td>
                    </tr>
                    <tr>
                      <td>5. Dual judge <span class="muted small">(hidden)</span></td>
                      <td><span class="stage-pill" :class="data.judge_pass === true ? 'pass' : data.judge_pass === false ? 'fail' : 'pending'">{{ data.judge_pass === null ? '—' : data.judge_pass ? 'pass' : 'fail' }}</span></td>
                      <td class="mono">{{ data.first_pass_judge != null ? data.first_pass_judge + 1 : '—' }}</td>
                    </tr>
                    <tr>
                      <td><strong>Overall</strong></td>
                      <td><span class="stage-pill" :class="data.overall_pass === true ? 'pass' : data.overall_pass === false ? 'fail' : 'pending'">{{ data.overall_pass === null ? '—' : data.overall_pass ? 'pass' : 'fail' }}</span></td>
                      <td></td>
                    </tr>
                  </tbody>
                </table>
                <div v-if="(data.schema_violations_parsed || []).length" style="margin-top: 12px;">
                  <div class="muted small" style="margin-bottom: 4px;">Schema violations:</div>
                  <ul class="violations">
                    <li v-for="(v, i) in data.schema_violations_parsed" :key="i"><code>{{ v }}</code></li>
                  </ul>
                </div>
                <table class="data" style="margin-top: 12px;">
                  <tbody>
                    <tr><th>judge_score (avg)</th><td class="mono">{{ data.judge_score != null ? data.judge_score.toFixed(3) : '—' }}</td></tr>
                    <tr><th>judge_score_a / b</th><td class="mono">
                      {{ data.judge_score_a != null ? data.judge_score_a.toFixed(3) : '—' }}
                      <span class="muted">/</span>
                      {{ data.judge_score_b != null ? data.judge_score_b.toFixed(3) : '—' }}
                    </td></tr>
                  </tbody>
                </table>
              </div>
            </section>

            <!-- PRACTITIONER METRICS (sidecar) -->
            <section class="card" :class="{ open: evalSections.metrics }">
              <button class="card-head" @click="toggleEval('metrics')">
                <span class="tag">METRICS</span>
                <span class="card-title">Practitioner metrics <span class="muted small">(sidecar — not pass/fail)</span></span>
                <span class="chev">{{ evalSections.metrics ? '▾' : '▸' }}</span>
              </button>
              <div v-if="evalSections.metrics" class="card-body">
                <table class="data">
                  <tbody>
                    <tr><th>total_return_pct</th><td class="mono">{{ data.total_return_pct != null ? data.total_return_pct.toFixed(2) + '%' : '—' }}</td></tr>
                    <tr><th>sharpe_ratio</th><td class="mono">{{ data.sharpe_ratio != null ? data.sharpe_ratio.toFixed(2) : '—' }}</td></tr>
                    <tr><th>max_drawdown_pct</th><td class="mono">{{ data.max_drawdown_pct != null ? data.max_drawdown_pct.toFixed(2) + '%' : '—' }}</td></tr>
                    <tr><th>num_trades</th><td class="mono">{{ data.num_trades != null ? data.num_trades : '—' }}</td></tr>
                    <tr><th>win_rate</th><td class="mono">{{ data.win_rate != null ? data.win_rate.toFixed(2) + '%' : '—' }}</td></tr>
                    <tr><th>starting_portfolio_value</th><td class="mono">{{ data.starting_portfolio_value != null ? '$' + data.starting_portfolio_value.toLocaleString() : '—' }}</td></tr>
                    <tr><th>final_portfolio_value</th><td class="mono">{{ data.final_portfolio_value != null ? '$' + data.final_portfolio_value.toLocaleString() : '—' }}</td></tr>
                    <tr><th>benchmark_return_pct</th><td class="mono">{{ data.benchmark_return_pct != null ? data.benchmark_return_pct.toFixed(2) + '%' : '—' }}</td></tr>
                  </tbody>
                </table>
              </div>
            </section>

            <!-- COST + TURN BUDGET -->
            <section class="card" :class="{ open: evalSections.cost }">
              <button class="card-head" @click="toggleEval('cost')">
                <span class="tag">COST</span>
                <span class="card-title">Cost, tokens, turn budget</span>
                <span class="chev">{{ evalSections.cost ? '▾' : '▸' }}</span>
              </button>
              <div v-if="evalSections.cost" class="card-body">
                <table class="data">
                  <tbody>
                    <tr><th>cost_usd</th><td class="mono">{{ data.total_cost_usd != null ? '$' + data.total_cost_usd.toFixed(4) : '—' }}</td></tr>
                    <tr><th>tokens (in / out)</th><td class="mono">{{ data.total_input_tokens }} / {{ data.total_output_tokens }}</td></tr>
                    <tr><th>turns used</th><td class="mono">{{ data.turns_used }} / {{ data.max_turns_allowed }}</td></tr>
                    <tr><th>RAG calls</th><td class="mono">{{ data.rag_call_count ?? '—' }}</td></tr>
                    <tr><th>code attempts</th><td class="mono">{{ data.code_attempt_count ?? '—' }}</td></tr>
                    <tr><th>wall_clock_seconds</th><td class="mono">{{ data.wall_clock_seconds?.toFixed(2) }}s</td></tr>
                    <tr><th>finish_reason</th><td><code>{{ data.finish_reason || '—' }}</code></td></tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          <!-- ============================================================ -->
          <!-- RAW TAB                                                       -->
          <!-- ============================================================ -->
          <div v-if="tab === 'raw'">
            <pre class="code-block"><code>{{ JSON.stringify(data, null, 2) }}</code></pre>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.header-id { font-size: 11px; color: var(--text-muted); margin-left: 8px; }
.tab-sub   { font-size: 11px; color: var(--text-muted); margin-left: 4px; }

/* Summary strip */
.strip {
  display: flex;
  gap: 12px;
  padding: 10px 12px;
  margin-bottom: 14px;
  background: var(--bg-chrome);
  border: 1px solid var(--border);
  border-radius: 6px;
  flex-wrap: wrap;
}
.strip-item { flex: 1; min-width: 100px; }
.strip-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted);
  font-weight: 600;
}
.strip-value {
  font-family: var(--font-mono);
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
  margin-top: 2px;
}

/* Sections */
.section { margin-bottom: 22px; }
.section-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.section-actions { display: flex; gap: 6px; }
.muted-small {
  font-size: 11px;
  color: var(--text-muted);
  margin: 0 0 8px;
}
.muted { color: var(--text-muted); }
.small { font-size: 11px; }

/* Generic card / expander */
.cards { display: flex; flex-direction: column; gap: 6px; }
.card {
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-elevated);
  overflow: hidden;
  margin-bottom: 8px;
}
.card.open { border-color: var(--border-strong); }
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  background: transparent;
  color: var(--text);
  border: none;
  padding: 8px 10px;
  text-align: left;
  cursor: pointer;
  font-size: 13px;
}
.card-head:hover { background: var(--bg-chrome); }
.card-title {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 13px;
  color: var(--text);
}
.card-body {
  padding: 10px 12px 14px;
  border-top: 1px solid var(--border);
}
.chev {
  color: var(--text-muted);
  flex: 0 0 auto;
  font-size: 12px;
}

/* Tags */
.tag {
  flex: 0 0 auto;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  background: var(--bg-chrome);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 6px;
  letter-spacing: 0.02em;
}
.kind-rag     { background: #dbeafe; border-color: #93c5fd; color: #1e40af; }
.kind-code    { background: #dcfce7; border-color: #86efac; color: #14532d; }
.kind-invalid { background: #fee2e2; border-color: #fca5a5; color: #991b1b; }
.final-tag    { background: #fef3c7; border-color: #fde68a; color: #92400e; }
.visible-tag  { background: #ecfdf5; border-color: #6ee7b7; color: #065f46; }
.hidden-tag   { background: #f3f4f6; border-color: #d1d5db; color: #4b5563; }
.fail-tag     { background: #fee2e2; border-color: #fca5a5; color: #991b1b; }
.turn-tag     { background: #e0e7ff; border-color: #a5b4fc; color: #3730a3; font-family: var(--font-mono); }

/* Stage mini-badges in turn header */
.stage-badges { display: inline-flex; gap: 3px; }
.stage-mini {
  display: inline-block;
  width: 18px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  font-size: 10px;
  font-weight: 700;
  border-radius: 3px;
  font-family: var(--font-mono);
}
.stage-mini.pass { background: #dcfce7; color: #14532d; border: 1px solid #86efac; }
.stage-mini.fail { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
.stage-mini.skip { background: #f3f4f6; color: #9ca3af; border: 1px solid #e5e7eb; }

/* Turn card spacing */
.turn-card.is-final { box-shadow: inset 3px 0 0 #f59e0b; }
.turn-title { flex: 1; font-size: 12px; }

/* Sub-accordions inside an expanded turn */
.sub {
  border: 1px solid var(--border);
  border-radius: 3px;
  margin-bottom: 6px;
  background: var(--bg);
}
.sub-head {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  padding: 6px 8px;
  cursor: pointer;
  text-align: left;
  font-size: 12px;
}
.sub-head:hover { background: var(--bg-chrome); }
.sub-title { font-weight: 600; color: var(--text); }
.sub-body {
  padding: 6px 10px 10px;
  border-top: 1px solid var(--border);
}

/* Code blocks: two flavours */
.code-block {
  margin: 4px 0 0;
  padding: 8px 10px;
  border-radius: 4px;
  max-height: 320px;
  overflow: auto;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
.code-light { background: #f8fafc; color: var(--text); }
.code-dark  { background: #0b1020; color: #e2e8f0; }

/* Pipeline tab */
.stage-card .stage-num {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  color: var(--text);
  background: var(--bg-elevated);
  border-color: var(--border-strong);
}
.stage-history { margin-bottom: 8px; }
.matrix-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.matrix-cell {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 38px;
  padding: 4px 6px;
  border-radius: 4px;
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 11px;
}
.matrix-cell.pass { background: #dcfce7; border-color: #86efac; color: #14532d; }
.matrix-cell.fail { background: #fee2e2; border-color: #fca5a5; color: #991b1b; }
.matrix-cell.skip { background: #f3f4f6; border-color: #e5e7eb; color: #9ca3af; }
.matrix-turn { font-size: 9px; font-weight: 600; }
.matrix-mark { font-weight: 700; font-size: 13px; }

/* Misc */
.tiny { padding: 3px 8px; font-size: 11px; }
.stage-pill.tiny { font-size: 9px; padding: 1px 5px; }
.excluded-box { margin-bottom: 12px; background: #f5f5f7; border-color: #ccc; color: #444; }
.violations {
  margin: 0; padding-left: 18px; font-size: 12px;
}
.violations code {
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #9a3412;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 11px;
}
details > summary { cursor: pointer; font-size: 12px; color: var(--text-muted); margin: 4px 0; }
</style>
