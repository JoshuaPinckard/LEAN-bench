<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  models:     { type: Array, required: true },
  conditions: { type: Array, required: true },
})
const emit = defineEmits(['error'])

const data = ref(null)
const lastUpdated = ref(null)
const tickRef = ref(0)
let timer = null

async function refresh() {
  try {
    data.value = await api.stats()
    lastUpdated.value = new Date()
  } catch (e) {
    emit('error', e.message)
  }
}

function tickClock() {
  tickRef.value++
}

onMounted(() => {
  refresh()
  timer = setInterval(refresh, 30_000)
  // Tick the "X seconds ago" label every 5 seconds without re-fetching
  setInterval(tickClock, 5_000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })

const secondsSince = computed(() => {
  tickRef.value  // dependency
  if (!lastUpdated.value) return null
  return Math.round((Date.now() - lastUpdated.value.getTime()) / 1000)
})

const sortedSpend = computed(() => {
  if (!data.value) return []
  return Object.entries(data.value.spend_by_model)
    .sort(([, a], [, b]) => b - a)
})

const maxSpend = computed(() => {
  const vals = sortedSpend.value.map(([, v]) => v)
  return Math.max(0.0001, ...vals)
})

function cellFor(model, condition) {
  if (!data.value) return null
  return data.value.pass_rate_matrix.find(c => c.model === model && c.condition === condition)
}

function cellClass(rate) {
  if (rate == null) return ''
  if (rate < 0.4) return 'low'
  if (rate < 0.7) return 'mid'
  return 'high'
}
</script>

<template>
  <div v-if="data">
    <div class="stat-cards">
      <div class="stat-card">
        <div class="label">Total spend</div>
        <div class="value">${{ data.total_spend_usd.toFixed(2) }}</div>
      </div>
      <div class="stat-card">
        <div class="label">Total calls</div>
        <div class="value">{{ data.total_calls.toLocaleString() }}</div>
      </div>
      <div class="stat-card">
        <div class="label">Total prompts</div>
        <div class="value">{{ data.total_prompts.toLocaleString() }}</div>
      </div>
      <div class="stat-card">
        <div class="label">Model freeze</div>
        <div class="value" style="font-size: 18px;">{{ data.frozen_date }}</div>
      </div>
    </div>

    <h3 style="margin-top: 0;">Spend by model</h3>
    <div class="bar-chart">
      <div v-if="!sortedSpend.length" style="color: var(--text-muted); padding: 20px; text-align: center;">
        No spend recorded yet.
      </div>
      <div v-else v-for="[name, amount] in sortedSpend" :key="name" class="bar-row">
        <div class="name">{{ name }}</div>
        <div class="bar" :style="{ width: ((amount / maxSpend) * 100) + '%' }"></div>
        <div class="amount">${{ amount.toFixed(4) }}</div>
      </div>
    </div>

    <h3>Pass rate matrix (judge_pass)</h3>
    <div class="matrix">
      <table>
        <thead>
          <tr>
            <th></th>
            <th v-for="c in conditions" :key="c.id">{{ c.id }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in models" :key="m.friendly_name">
            <td class="label">{{ m.friendly_name }}</td>
            <td v-for="c in conditions" :key="c.id"
                class="cell"
                :class="cellClass(cellFor(m.friendly_name, c.id)?.pass_rate)">
              <template v-if="cellFor(m.friendly_name, c.id)">
                <template v-if="cellFor(m.friendly_name, c.id).pass_rate != null">
                  {{ Math.round(cellFor(m.friendly_name, c.id).pass_rate * 100) }}%
                </template>
                <template v-else>—</template>
                <span class="n">(n={{ cellFor(m.friendly_name, c.id).n }})</span>
              </template>
              <template v-else>—</template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="last-updated">
      Last updated: {{ secondsSince != null ? secondsSince + 's ago' : '—' }}
      (auto-refreshes every 30s)
    </div>
  </div>
  <div v-else style="padding: 40px; text-align: center; color: var(--text-muted);">
    <span class="spinner"></span> Loading stats…
  </div>
</template>
