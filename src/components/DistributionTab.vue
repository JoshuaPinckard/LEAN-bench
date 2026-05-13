<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api.js'

const emit = defineEmits(['error'])
const data    = ref(null)
const loading = ref(false)
const lastFetched = ref(null)

async function load() {
  loading.value = true
  try {
    data.value = await api.distribution()
    lastFetched.value = new Date().toLocaleTimeString()
  } catch (e) {
    emit('error', e.message)
  } finally {
    loading.value = false
  }
}
onMounted(load)

// Render-helpers
const sections = computed(() => {
  if (!data.value) return []
  return [
    { key: 'by_strategy_type',         title: 'Strategy type',          order: null },
    { key: 'by_strategy_complexity',   title: 'Strategy complexity',    order: ['1','2','3'] },
    { key: 'by_api_complexity',        title: 'API complexity',         order: ['1','2','3'] },
    { key: 'by_implementation_type',   title: 'Implementation type',    order: null },
    { key: 'by_universe_type',         title: 'Universe type',          order: null },
    { key: 'by_securities_type',       title: 'Securities type',        order: null },
    { key: 'by_resolution',            title: 'Resolution',             order: ['high_frequency','intraday','daily'] },
    { key: 'by_evaluation_mode',       title: 'Evaluation mode',        order: null },
    { key: 'by_interpretation_strictness', title: 'Interpretation strictness',
      order: ['unambiguous','mild_variation','broad_interpretation'] },
  ]
})

function rowsFor(section) {
  const obj = data.value[section.key] || {}
  let entries = Object.entries(obj)
  if (section.order) {
    const orderMap = Object.fromEntries(section.order.map((v, i) => [v, i]))
    entries = entries.sort((a, b) => {
      const ai = orderMap[a[0]] ?? 99
      const bi = orderMap[b[0]] ?? 99
      return ai - bi || b[1] - a[1]
    })
  } else {
    entries = entries.sort((a, b) => b[1] - a[1])
  }
  const max = Math.max(1, ...entries.map(e => e[1]))
  return entries.map(([k, n]) => ({ label: k, n, pct: (n / max) * 100 }))
}

const indicatorRows = computed(() => {
  if (!data.value) return []
  const obj = data.value.indicator_frequency || {}
  const entries = Object.entries(obj).sort((a, b) => b[1] - a[1])
  const max = Math.max(1, ...entries.map(e => e[1]))
  return entries.map(([k, n]) => ({ label: k, n, pct: (n / max) * 100 }))
})
</script>

<template>
  <div class="dist-tab">
    <div class="dist-header">
      <h2>Distribution</h2>
      <div class="dist-meta">
        <span v-if="data">Total: <strong>{{ data.total }}</strong> curated prompts</span>
        <span v-if="lastFetched" class="muted">refreshed {{ lastFetched }}</span>
        <button class="secondary" :disabled="loading" @click="load">
          {{ loading ? 'Loading…' : 'Refresh' }}
        </button>
      </div>
    </div>

    <div v-if="!data && loading" class="empty">Loading distribution…</div>
    <div v-else-if="!data" class="empty">No data yet.</div>

    <div v-else class="dist-grid">
      <section v-for="s in sections" :key="s.key" class="dist-card">
        <h4>{{ s.title }}</h4>
        <table>
          <tr v-for="row in rowsFor(s)" :key="row.label">
            <td class="lbl">{{ row.label }}</td>
            <td class="bar-cell">
              <div class="bar" :style="{ width: row.pct + '%' }"></div>
            </td>
            <td class="n">{{ row.n }}</td>
          </tr>
          <tr v-if="!rowsFor(s).length">
            <td colspan="3" class="muted">— no data —</td>
          </tr>
        </table>
      </section>

      <section class="dist-card dist-card-wide">
        <h4>Indicator frequency</h4>
        <table>
          <tr v-for="row in indicatorRows" :key="row.label">
            <td class="lbl">{{ row.label }}</td>
            <td class="bar-cell">
              <div class="bar" :style="{ width: row.pct + '%' }"></div>
            </td>
            <td class="n">{{ row.n }}</td>
          </tr>
          <tr v-if="!indicatorRows.length">
            <td colspan="3" class="muted">— no indicators logged yet —</td>
          </tr>
        </table>
      </section>
    </div>
  </div>
</template>

<style scoped>
.dist-tab { padding: 16px 24px; max-width: 1400px; margin: 0 auto; }
.dist-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 16px; }
.dist-meta { display: flex; gap: 14px; align-items: center; font-size: 13px; }
.muted { color: var(--text-muted, #888); }
.empty { padding: 60px 0; text-align: center; color: var(--text-muted, #888); }

.dist-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}
.dist-card-wide { grid-column: 1 / -1; }

.dist-card {
  background: var(--bg-chrome, #fafafa);
  border: 1px solid var(--border, #e5e5e5);
  border-radius: 6px;
  padding: 12px 14px;
}
.dist-card h4 {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted, #888);
}
.dist-card table { width: 100%; border-collapse: collapse; font-size: 13px; }
.dist-card td { padding: 4px 0; vertical-align: middle; }
.lbl { width: 35%; word-break: break-word; }
.bar-cell { width: 55%; padding-right: 8px !important; }
.bar { height: 14px; background: #4f46e5; border-radius: 2px; min-width: 1px; }
.n { width: 10%; text-align: right; font-variant-numeric: tabular-nums; }
</style>
