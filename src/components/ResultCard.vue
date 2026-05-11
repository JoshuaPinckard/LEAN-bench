<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  result:    { type: Object, required: true },
  condition: { type: Object, required: true },
  provider:  { type: String, required: true },
})

defineEmits(['view-details'])

const expanded = ref(false)

const status = computed(() => {
  const r = props.result
  if (r.status === 'error') return 'error'
  if (r.overall_pass === true) return 'pass'
  if (r.compile_pass === false) return 'fail'
  return 'pending'
})

const statusIcon = computed(() => {
  switch (status.value) {
    case 'pass':  return '✓'
    case 'fail':  return '✗'
    case 'error': return '⚠'
    default:      return '·'
  }
})

function stageClass(value) {
  if (value === true)  return 'pass'
  if (value === false) return 'fail'
  return 'pending'
}

function formatCost(c) {
  if (c == null) return '—'
  return '$' + c.toFixed(4)
}
function formatLatency(ms) {
  return (ms / 1000).toFixed(1) + 's'
}
</script>

<template>
  <div class="result-card">
    <div class="card-header">
      <span class="status-icon" :class="status">{{ statusIcon }}</span>
      <span class="model-name">{{ result.model }}</span>
      <span class="badge" :class="provider">{{ provider }}</span>
    </div>

    <template v-if="result.status === 'error'">
      <div class="error-box">{{ result.error }}</div>
    </template>

    <template v-else>
      <div class="pipeline-pills">
        <span class="stage-pill" :class="stageClass(result.compile_pass)">compile</span>
        <span class="stage-pill" :class="stageClass(result.backtest_pass)">backtest</span>
        <span class="stage-pill" :class="stageClass(result.trade_pass)">trade</span>
        <span class="stage-pill" :class="stageClass(result.judge_pass)">judge</span>
      </div>

      <div class="card-meta">
        <span>{{ formatCost(result.cost_usd) }}</span>
        <span>{{ formatLatency(result.latency_ms) }}</span>
        <span>{{ result.input_tokens }} in / {{ result.output_tokens }} out</span>
        <span v-if="condition.max_turns > 1">turns: {{ result.turns_used }}/{{ condition.max_turns }}</span>
      </div>

      <button class="code-toggle" @click="expanded = !expanded">
        {{ expanded ? '▼' : '▶' }} {{ result.generated_code ? 'code' : 'no code extracted' }}
      </button>
      <div v-if="result.generated_code" class="code-block" :class="{ expanded }">
        <pre><code>{{ result.generated_code }}</code></pre>
      </div>
    </template>

    <div class="card-footer">
      <span v-if="result.failure_category_l1" class="failure-tag">
        {{ result.failure_category_l1 }}<span v-if="result.failure_category_l2">.{{ result.failure_category_l2 }}</span>
      </span>
      <span v-else></span>
      <button class="secondary" style="padding: 4px 10px; font-size: 12px;" @click="$emit('view-details', result.call_id)">
        View details
      </button>
    </div>
  </div>
</template>
