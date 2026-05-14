<script setup>
import { ref, watch } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  callId: { type: String, default: null },
})
defineEmits(['close'])

const tab = ref('code')
const data = ref(null)
const error = ref(null)
const loading = ref(false)

async function load(id) {
  data.value = null
  error.value = null
  if (!id) return
  loading.value = true
  try {
    data.value = await api.getCall(id)
    tab.value = 'code'
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
        <button class="tab" :class="{ active: tab === 'code' }" @click="tab = 'code'">Code</button>
        <button class="tab" :class="{ active: tab === 'eval' }" @click="tab = 'eval'">Evaluation</button>
        <button v-if="data.tool_agentic_loop" class="tab" :class="{ active: tab === 'turns' }" @click="tab = 'turns'">
          Trajectory ({{ data.turns?.length || 0 }})
        </button>
        <button class="tab" :class="{ active: tab === 'raw' }" @click="tab = 'raw'">Raw</button>
      </div>

      <div class="modal-body">
        <div v-if="loading"><span class="spinner"></span> Loading…</div>
        <div v-else-if="error" class="error-box">{{ error }}</div>

        <template v-else-if="data">
          <div v-if="tab === 'code'">
            <button class="secondary" style="margin-bottom: 8px; padding: 4px 10px; font-size: 12px;"
                    @click="copy(data.final_code_sha256 ? data.turns?.[data.turns.length - 1]?.response_code_extracted : null)">
              Copy
            </button>
            <pre class="code-block" style="max-height: none;"><code>{{
              data.turns?.[data.turns.length - 1]?.response_code_extracted
                || (data.turns?.length ? '(no code extracted)' : '(single-turn call — code not stored separately; see Raw tab)')
            }}</code></pre>
          </div>

          <div v-if="tab === 'eval'">
            <table class="data" style="margin-bottom: 16px;">
              <tbody>
                <tr><th style="width: 200px;">compile_pass</th><td>{{ data.compile_pass }}</td></tr>
                <tr><th>backtest_pass</th><td>{{ data.backtest_pass }}</td></tr>
                <tr><th>trade_pass</th><td>{{ data.trade_pass }}</td></tr>
                <tr><th>judge_pass</th><td>{{ data.judge_pass }}</td></tr>
                <tr><th>overall_pass</th><td>{{ data.overall_pass }}</td></tr>
                <tr><th>first_failed_stage</th><td>{{ data.first_failed_stage || '—' }}</td></tr>
                <tr><th>failure_category</th><td>{{ data.failure_category_l1 ? `${data.failure_category_l1}.${data.failure_category_l2 || ''}` : '—' }}</td></tr>
                <tr><th>total_return_pct</th><td>{{ data.total_return_pct != null ? data.total_return_pct.toFixed(2) + '%' : '—' }}</td></tr>
                <tr><th>profit_loss_usd</th><td>{{
                  data.final_portfolio_value != null && data.starting_portfolio_value != null
                    ? (data.final_portfolio_value - data.starting_portfolio_value >= 0 ? '+$' : '-$')
                      + Math.abs(data.final_portfolio_value - data.starting_portfolio_value).toFixed(2)
                    : '—'
                }}</td></tr>
                <tr><th>starting_portfolio_value</th><td>{{ data.starting_portfolio_value != null ? '$' + data.starting_portfolio_value.toFixed(2) : '—' }}</td></tr>
                <tr><th>final_portfolio_value</th><td>{{ data.final_portfolio_value != null ? '$' + data.final_portfolio_value.toFixed(2) : '—' }}</td></tr>
                <tr><th>benchmark_return_pct</th><td>{{ data.benchmark_return_pct != null ? data.benchmark_return_pct.toFixed(2) + '%' : '—' }}</td></tr>
                <tr><th>sharpe_ratio</th><td>{{ data.sharpe_ratio != null ? data.sharpe_ratio.toFixed(2) : '—' }}</td></tr>
                <tr><th>max_drawdown_pct</th><td>{{ data.max_drawdown_pct != null ? data.max_drawdown_pct.toFixed(2) + '%' : '—' }}</td></tr>
                <tr><th>num_trades</th><td>{{ data.num_trades != null ? data.num_trades : '—' }}</td></tr>
                <tr><th>win_rate</th><td>{{ data.win_rate != null ? data.win_rate.toFixed(1) + '%' : '—' }}</td></tr>
                <tr><th>cost_usd</th><td>{{ data.total_cost_usd != null ? '$' + data.total_cost_usd.toFixed(4) : '—' }}</td></tr>
                <tr><th>tokens (in / out)</th><td>{{ data.total_input_tokens }} / {{ data.total_output_tokens }}</td></tr>
                <tr><th>turns_used</th><td>{{ data.turns_used }} / {{ data.max_turns_allowed }}</td></tr>
                <tr><th>wall_clock_seconds</th><td>{{ data.wall_clock_seconds?.toFixed(2) }}s</td></tr>
              </tbody>
            </table>
            <div v-if="data.error" class="error-box">{{ data.error }}</div>
          </div>

          <div v-if="tab === 'turns'">
            <div v-if="!data.turns?.length" style="color: var(--text-muted);">No per-turn rows recorded.</div>
            <div v-for="turn in data.turns" :key="turn.turn_id" style="margin-bottom: 24px;">
              <h4 style="margin: 0 0 6px;">
                Turn {{ turn.turn_index + 1 }}
                <span class="stage-pill" :class="turn.compile_pass === true ? 'pass' : turn.compile_pass === false ? 'fail' : 'pending'" style="margin-left: 8px;">
                  compile: {{ turn.compile_pass === null ? '—' : turn.compile_pass ? 'pass' : 'fail' }}
                </span>
                <span style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); margin-left: 8px;">
                  {{ turn.response_tokens_in }} in / {{ turn.response_tokens_out }} out · {{ turn.wall_clock_seconds?.toFixed(2) }}s
                </span>
              </h4>
              <details>
                <summary style="cursor: pointer; color: var(--text-muted); font-size: 12px;">submitted code</summary>
                <pre class="code-block" style="max-height: 300px;"><code>{{ turn.response_code_extracted || '(no code in this turn)' }}</code></pre>
              </details>
              <div v-if="turn.feedback_text" style="margin-top: 8px;">
                <div style="font-size: 12px; color: var(--text-muted); font-weight: 600;">Feedback sent back to model:</div>
                <pre class="code-block" style="background: #fffbeb; max-height: 200px;"><code>{{ turn.feedback_text }}</code></pre>
              </div>
            </div>
          </div>

          <div v-if="tab === 'raw'">
            <pre class="code-block" style="max-height: none;"><code>{{ JSON.stringify(data, null, 2) }}</code></pre>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
