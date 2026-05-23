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

// Expansion state for the Transcript tab: keep collapsed by default so the
// view stays glanceable; individual cards open on click.
const expandedRag = ref(new Set())
const expandedCompile = ref(new Set())
const showAllTurns = ref(false)
const showSystemPrompt = ref(false)
const showUserPrompt = ref(true)

async function load(id) {
  data.value = null
  error.value = null
  if (!id) return
  loading.value = true
  try {
    data.value = await api.getCall(id)
    tab.value = 'transcript'
    expandedRag.value = new Set()
    expandedCompile.value = new Set()
    showAllTurns.value = false
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

// NOTE: Vue 3 auto-unwraps refs in templates, so a generic toggle(ref, key)
// helper would receive the inner Set, not the ref — and `set.value = ...`
// would silently no-op (no update, expand body never shows). Close over each
// ref directly instead.
function toggleRag(i) {
  const s = new Set(expandedRag.value)
  if (s.has(i)) s.delete(i); else s.add(i)
  expandedRag.value = s
}
function toggleCompile(i) {
  const s = new Set(expandedCompile.value)
  if (s.has(i)) s.delete(i); else s.add(i)
  expandedCompile.value = s
}

const transcript = computed(() => data.value?.transcript || null)
const finalTurn = computed(() => transcript.value?.final_turn || null)
const finalCode = computed(() => {
  if (finalTurn.value?.response_code_extracted) return finalTurn.value.response_code_extracted
  // Fallback for single-turn calls (no turns rows).
  return data.value?.generated_code || null
})

function exitBadge(status) {
  if (status === 'completed') return { cls: 'pass',    label: 'completed' }
  if (status === 'timeout')   return { cls: 'fail',    label: 'timeout' }
  if (status === 'docker_error') return { cls: 'fail', label: 'docker_error' }
  if (status === 'infra_error')  return { cls: 'fail', label: 'infra_error' }
  return { cls: 'pending', label: status || '—' }
}

// Pull the highest-signal line out of a compiler log tail for the collapsed view.
function logHighlight(tail) {
  if (!tail) return ''
  const lines = tail.split(/\r?\n/).filter(Boolean)
  // Prefer the trailer line.
  for (let i = lines.length - 1; i >= 0; i--) {
    const ln = lines[i].trim()
    if (/^(LEAN_RUN_FINISHED|TIMEOUT_EXCEEDED|INFRASTRUCTURE_ERROR|ORDERS_PLACED:)/.test(ln)) {
      return ln
    }
  }
  // Otherwise an error line.
  for (let i = lines.length - 1; i >= 0; i--) {
    if (/ERROR::/i.test(lines[i])) return lines[i].trim()
  }
  return lines[lines.length - 1].slice(0, 160)
}
</script>

<template>
  <div v-if="callId" class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal">
      <div class="modal-header">
        <h2 v-if="data">
          {{ data.model_id }}
          · {{ data.condition_id }}
          · trial {{ data.trial_index }}
          <span class="mono" style="font-size: 11px; color: var(--text-muted); margin-left: 8px;">{{ data.call_id }}</span>
        </h2>
        <h2 v-else>Loading…</h2>
        <button class="icon" @click="$emit('close')" style="font-size: 18px;">✕</button>
      </div>

      <div class="modal-tabs" v-if="data">
        <button class="tab" :class="{ active: tab === 'transcript' }" @click="tab = 'transcript'">
          Transcript
          <span v-if="transcript" class="mono" style="font-size: 11px; color: var(--text-muted); margin-left: 4px;">
            <template v-if="data.tool_agentic_loop">
              {{ transcript.rag_count }} RAG · {{ transcript.compile_count }} compile · {{ transcript.total_turns }} turns
            </template>
            <template v-else>one-shot</template>
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
          <!-- =================== TRANSCRIPT TAB =================== -->
          <div v-if="tab === 'transcript'" class="transcript">
            <template v-if="transcript">
              <!-- Prompts the model actually saw -->
              <section class="ts-section">
                <h3 class="ts-section-title">Prompts sent to model</h3>
                <div class="ts-cards">
                  <div class="ts-card" :class="{ open: showUserPrompt }">
                    <button class="ts-card-head" @click="showUserPrompt = !showUserPrompt">
                      <span class="ts-turn-tag mono">USER</span>
                      <span class="ts-card-title">
                        Initial user message
                        <span style="color: var(--text-muted);">
                          ({{ transcript.initial_user_message ? transcript.initial_user_message.length : 0 }} chars)
                        </span>
                      </span>
                      <span class="ts-chev">{{ showUserPrompt ? '▾' : '▸' }}</span>
                    </button>
                    <div v-if="showUserPrompt" class="ts-card-body">
                      <pre class="code-block" style="max-height: 320px; background: #f8fafc;"><code>{{ transcript.initial_user_message || '(not recorded)' }}</code></pre>
                    </div>
                  </div>
                  <div class="ts-card" :class="{ open: showSystemPrompt }">
                    <button class="ts-card-head" @click="showSystemPrompt = !showSystemPrompt">
                      <span class="ts-turn-tag mono">SYSTEM</span>
                      <span class="ts-card-title">
                        System prompt
                        <span style="color: var(--text-muted);">
                          (sha {{ (data.system_prompt_sha || '').slice(0, 8) || '—' }})
                        </span>
                      </span>
                      <span class="ts-chev">{{ showSystemPrompt ? '▾' : '▸' }}</span>
                    </button>
                    <div v-if="showSystemPrompt" class="ts-card-body">
                      <pre class="code-block" style="max-height: 320px; background: #f8fafc;"><code>{{ transcript.system_prompt || '(unavailable)' }}</code></pre>
                    </div>
                  </div>
                </div>
              </section>

              <!-- Single-turn note: no agent loop, the rest of the sections
                   only make sense for agentic calls. -->
              <div v-if="transcript.total_turns === 0" style="color: var(--text-muted); padding: 8px 0;">
                Single-turn call — no agent loop. See the Code tab for the
                model's response.
              </div>

              <!-- Summary strip -->
              <div v-if="transcript.total_turns > 0" class="ts-strip">
                <div class="ts-strip-item">
                  <div class="ts-label">RAG queries</div>
                  <div class="ts-value">{{ transcript.rag_count }}</div>
                </div>
                <div class="ts-strip-item">
                  <div class="ts-label">Compiler runs</div>
                  <div class="ts-value">{{ transcript.compile_count }}</div>
                </div>
                <div class="ts-strip-item">
                  <div class="ts-label">Final code at turn</div>
                  <div class="ts-value">
                    {{ transcript.final_turn_index != null ? (transcript.final_turn_index + 1) : '—' }}
                    <span style="color: var(--text-muted); font-weight: 400;">
                      / {{ transcript.total_turns }}
                    </span>
                  </div>
                </div>
              </div>

              <!-- RAG events (defaults collapsed; click to see chunks) -->
              <section class="ts-section" v-if="transcript.rag_count > 0">
                <h3 class="ts-section-title">RAG queries ({{ transcript.rag_count }})</h3>
                <div class="ts-cards">
                  <div v-for="(ev, i) in transcript.rag_events" :key="'rag-' + i"
                       class="ts-card" :class="{ open: expandedRag.has(i) }">
                    <button class="ts-card-head" @click="toggleRag(i)">
                      <span class="ts-turn-tag mono">T{{ ev.turn_index + 1 }}</span>
                      <span class="ts-card-title">{{ ev.query || '(empty query)' }}</span>
                      <span class="mono" style="color: var(--text-muted); font-size: 11px;">
                        {{ ev.output_len }} chars
                      </span>
                      <span class="ts-chev">{{ expandedRag.has(i) ? '▾' : '▸' }}</span>
                    </button>
                    <div v-if="expandedRag.has(i)" class="ts-card-body">
                      <pre class="code-block" style="max-height: 320px; background: #f8fafc;"><code>{{ ev.output_preview }}</code></pre>
                    </div>
                  </div>
                </div>
              </section>

              <!-- Compiler runs (defaults collapsed; click for log tail) -->
              <section class="ts-section" v-if="transcript.compile_count > 0">
                <h3 class="ts-section-title">Compiler runs ({{ transcript.compile_count }})</h3>
                <div class="ts-cards">
                  <div v-for="(ev, i) in transcript.compile_events" :key="'cc-' + i"
                       class="ts-card" :class="{ open: expandedCompile.has(i) }">
                    <button class="ts-card-head" @click="toggleCompile(i)">
                      <span class="ts-turn-tag mono">T{{ ev.turn_index + 1 }}</span>
                      <span class="stage-pill" :class="exitBadge(ev.exit_status).cls" style="font-size: 10px;">
                        {{ exitBadge(ev.exit_status).label }}
                      </span>
                      <span class="ts-card-title mono" style="font-size: 12px;">
                        {{ logHighlight(ev.log_tail) || '(no log captured)' }}
                      </span>
                      <span class="mono" style="color: var(--text-muted); font-size: 11px;">
                        {{ ev.code_chars }} chars · {{ ev.code_sha8 || '—' }}
                      </span>
                      <span class="ts-chev">{{ expandedCompile.has(i) ? '▾' : '▸' }}</span>
                    </button>
                    <div v-if="expandedCompile.has(i)" class="ts-card-body">
                      <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 4px;">
                        Log tail (last {{ ev.log_tail?.length || 0 }} chars):
                      </div>
                      <pre class="code-block" style="max-height: 380px; background: #0b1020; color: #e2e8f0;"><code>{{ ev.log_tail || '(empty)' }}</code></pre>
                    </div>
                  </div>
                </div>
              </section>

              <!-- Final round -->
              <section class="ts-section" v-if="transcript.total_turns > 0">
                <h3 class="ts-section-title">
                  Final round
                  <span v-if="finalTurn" style="color: var(--text-muted); font-weight: 400; font-size: 13px;">
                    — turn {{ finalTurn.turn_index + 1 }}/{{ transcript.total_turns }}
                    · {{ finalTurn.response_tokens_in }} in / {{ finalTurn.response_tokens_out }} out
                    · {{ finalTurn.wall_clock_seconds?.toFixed(2) }}s
                  </span>
                </h3>

                <div v-if="finalTurn" style="margin-bottom: 10px;">
                  <div class="ts-label" style="margin-bottom: 4px;">Assistant response</div>
                  <pre class="code-block" style="max-height: 320px;"><code>{{ finalTurn.response_text || '(no assistant text on final turn)' }}</code></pre>
                </div>

                <div>
                  <div class="ts-label" style="margin-bottom: 4px;">Extracted code</div>
                  <button class="secondary" style="margin-bottom: 6px; padding: 4px 10px; font-size: 12px;"
                          @click="copy(finalCode)" :disabled="!finalCode">Copy</button>
                  <pre class="code-block" style="max-height: none;"><code>{{ finalCode || '(no code extracted from final round)' }}</code></pre>
                </div>
              </section>

              <!-- Optional: all-turns table (off by default — keeps the view clean) -->
              <section class="ts-section" v-if="transcript.total_turns > 0">
                <button class="secondary" @click="showAllTurns = !showAllTurns"
                        style="padding: 4px 10px; font-size: 12px;">
                  {{ showAllTurns ? '▼' : '▶' }} All {{ transcript.total_turns }} turns ({{ showAllTurns ? 'hide' : 'show' }})
                </button>
                <div v-if="showAllTurns" style="margin-top: 8px;">
                  <table class="data">
                    <thead>
                      <tr>
                        <th style="width: 50px;">#</th>
                        <th>compile</th>
                        <th>tool events</th>
                        <th>code emitted</th>
                        <th>tokens (in/out)</th>
                        <th>wall</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="t in data.turns" :key="t.turn_id">
                        <td class="mono">{{ t.turn_index + 1 }}</td>
                        <td>
                          <span class="stage-pill" :class="t.compile_pass === true ? 'pass' : t.compile_pass === false ? 'fail' : 'pending'"
                                style="font-size: 10px;">
                            {{ t.compile_pass === null ? '—' : t.compile_pass ? 'pass' : 'fail' }}
                          </span>
                        </td>
                        <td class="mono" style="font-size: 11px;">
                          <span v-if="!t.tool_events?.length" style="color: var(--text-muted);">—</span>
                          <span v-for="ev in t.tool_events" :key="ev.name"
                                style="margin-right: 6px;"
                                :title="ev.name === 'qc_docs_retrieve' ? ev.query : ev.code_sha8">
                            {{ ev.name === 'qc_docs_retrieve' ? 'RAG' : 'COMPILE' }}<span v-if="ev.is_error" style="color: var(--fail);">!</span>
                          </span>
                        </td>
                        <td>
                          <span v-if="t.response_code_extracted" class="stage-pill pass" style="font-size: 10px;">code</span>
                          <span v-else style="color: var(--text-muted);">—</span>
                          <span v-if="t.is_final_turn" class="stage-pill" style="font-size: 10px; margin-left: 4px; background: #fef3c7; border-color: #fde68a; color: #92400e;">
                            final
                          </span>
                        </td>
                        <td class="mono" style="font-size: 11px;">{{ t.response_tokens_in }} / {{ t.response_tokens_out }}</td>
                        <td class="mono" style="font-size: 11px;">{{ t.wall_clock_seconds?.toFixed(2) }}s</td>
                        <td></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </section>
            </template>
          </div>

          <!-- =================== CODE TAB =================== -->
          <div v-if="tab === 'code'">
            <button class="secondary" style="margin-bottom: 8px; padding: 4px 10px; font-size: 12px;"
                    @click="copy(finalCode)">
              Copy
            </button>
            <pre class="code-block" style="max-height: none;"><code>{{ finalCode || '(no code extracted)' }}</code></pre>
          </div>

          <!-- =================== EVAL TAB =================== -->
          <div v-if="tab === 'eval'">
            <div v-if="data.status === 'excluded'" class="error-box"
                 style="margin-bottom: 12px; background: #f5f5f7; border-color: #ccc; color: #444;">
              <strong>Excluded by design.</strong>
              Reason: <code>{{ data.excluded_reason || 'unspecified' }}</code>.
              No provider, backtest, or judge call was made.
            </div>
            <div v-if="data.judge_error" class="error-box" style="margin-bottom: 12px;">
              <strong>Judge failed:</strong> {{ data.judge_error }}
            </div>
            <table class="data" style="margin-bottom: 12px;">
              <tbody>
                <tr><th style="width: 200px;">status</th><td>{{ data.status || '—' }}</td></tr>
                <tr><th>benchmark_version</th><td><code>{{ data.benchmark_version || '—' }}</code></td></tr>
                <tr><th>judge_version</th><td><code>{{ data.judge_version || '—' }}</code></td></tr>
                <tr><th>judge_threshold</th><td><code>{{ data.judge_threshold ?? '—' }}</code></td></tr>
                <tr><th>artifact_sha256</th><td><code style="font-size: 11px;">{{ data.artifact_sha256 || '—' }}</code></td></tr>
              </tbody>
            </table>
            <table class="data" style="margin-bottom: 16px;">
              <tbody>
                <tr><th style="width: 200px;">compile_pass</th><td>{{ data.compile_pass }}</td></tr>
                <tr><th>backtest_pass</th><td>{{ data.backtest_pass }}</td></tr>
                <tr><th>trade_pass</th><td>{{ data.trade_pass }}</td></tr>
                <tr><th>schema_pass</th><td>{{ data.schema_pass }}</td></tr>
                <tr><th>judge_pass</th><td>{{ data.judge_pass != null ? data.judge_pass : (data.judge_error ? 'failed' : '—') }}</td></tr>
                <tr><th>overall_pass</th><td>{{ data.overall_pass }}</td></tr>
                <tr><th>judge_score (avg)</th><td>{{ data.judge_score != null ? data.judge_score.toFixed(3) : '—' }}</td></tr>
                <tr><th>judge_score_a / b</th><td>
                  <span class="mono">{{ data.judge_score_a != null ? data.judge_score_a.toFixed(3) : '—' }}</span>
                  <span style="color: var(--text-muted); margin: 0 6px;">/</span>
                  <span class="mono">{{ data.judge_score_b != null ? data.judge_score_b.toFixed(3) : '—' }}</span>
                </td></tr>
                <tr><th>total_return_pct</th><td>{{ data.total_return_pct != null ? data.total_return_pct.toFixed(2) + '%' : '—' }}</td></tr>
                <tr><th>sharpe_ratio</th><td>{{ data.sharpe_ratio != null ? data.sharpe_ratio.toFixed(2) : '—' }}</td></tr>
                <tr><th>max_drawdown_pct</th><td>{{ data.max_drawdown_pct != null ? data.max_drawdown_pct.toFixed(2) + '%' : '—' }}</td></tr>
                <tr><th>num_trades</th><td>{{ data.num_trades != null ? data.num_trades : '—' }}</td></tr>
                <tr><th>cost_usd</th><td>{{ data.total_cost_usd != null ? '$' + data.total_cost_usd.toFixed(4) : '—' }}</td></tr>
                <tr><th>tokens (in / out)</th><td>{{ data.total_input_tokens }} / {{ data.total_output_tokens }}</td></tr>
                <tr><th>turns_used</th><td>{{ data.turns_used }} / {{ data.max_turns_allowed }}</td></tr>
                <tr><th>wall_clock_seconds</th><td>{{ data.wall_clock_seconds?.toFixed(2) }}s</td></tr>
              </tbody>
            </table>
            <div v-if="data.error" class="error-box">{{ data.error }}</div>
          </div>

          <!-- =================== RAW TAB =================== -->
          <div v-if="tab === 'raw'">
            <pre class="code-block" style="max-height: none;"><code>{{ JSON.stringify(data, null, 2) }}</code></pre>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.transcript .ts-strip {
  display: flex;
  gap: 16px;
  padding: 12px 14px;
  margin-bottom: 16px;
  background: var(--bg-chrome);
  border: 1px solid var(--border);
  border-radius: 6px;
}
.transcript .ts-strip-item { flex: 1; }
.transcript .ts-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted);
  font-weight: 600;
}
.transcript .ts-value {
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}

.transcript .ts-section { margin-bottom: 22px; }
.transcript .ts-section-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: 0.01em;
}

.transcript .ts-cards {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.transcript .ts-card {
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-elevated);
  overflow: hidden;
}
.transcript .ts-card.open { border-color: var(--border-strong); }
.transcript .ts-card-head {
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
.transcript .ts-card-head:hover { background: var(--bg-chrome); }
.transcript .ts-turn-tag {
  flex: 0 0 auto;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  background: var(--bg-chrome);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 5px;
}
.transcript .ts-card-title {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 13px;
  color: var(--text);
}
.transcript .ts-chev {
  color: var(--text-muted);
  flex: 0 0 auto;
}
.transcript .ts-card-body {
  padding: 8px 10px 12px;
  border-top: 1px solid var(--border);
}
</style>
