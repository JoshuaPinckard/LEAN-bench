<script setup>
import { ref, onMounted } from 'vue'
import { api } from './api.js'
import GenerateTab from './components/GenerateTab.vue'
import PromptsTab from './components/PromptsTab.vue'
import DistributionTab from './components/DistributionTab.vue'
import StatsTab from './components/StatsTab.vue'

const tab = ref('generate')
const models = ref([])
const conditions = ref([])
const frozenDate = ref('')
const bootError = ref(null)
const toast = ref(null)

function showError(msg) { toast.value = msg }
function clearToast()   { toast.value = null }

onMounted(async () => {
  try {
    const [m, c] = await Promise.all([api.models(), api.conditions()])
    models.value = m.models
    frozenDate.value = m.frozen_date
    conditions.value = c.conditions
  } catch (err) {
    bootError.value = err.message
  }
})
</script>

<template>
  <div v-if="bootError" class="full-page-error">
    <h2>Backend not reachable</h2>
    <p>{{ bootError }}</p>
    <p>Start the FastAPI server with:</p>
    <p class="mono">.\start.ps1</p>
    <p class="mono">(or: uvicorn backend.app:app --reload --port 8010)</p>
    <p>then refresh this page.</p>
  </div>

  <template v-else>
    <nav class="app-nav">
      <h1>LEAN-Bench</h1>
      <div class="tabs">
        <button class="tab" :class="{ active: tab === 'generate'    }" @click="tab = 'generate'">Generate</button>
        <button class="tab" :class="{ active: tab === 'prompts'     }" @click="tab = 'prompts'">Prompts</button>
        <button class="tab" :class="{ active: tab === 'distribution'}" @click="tab = 'distribution'">Distribution</button>
        <button class="tab" :class="{ active: tab === 'stats'       }" @click="tab = 'stats'">Stats</button>
      </div>
      <div class="frozen">frozen: {{ frozenDate }}</div>
    </nav>

    <main class="app-body">
      <GenerateTab v-if="tab === 'generate'" :models="models" :conditions="conditions" @error="showError" />
      <PromptsTab     v-if="tab === 'prompts'"      @error="showError" />
      <DistributionTab v-if="tab === 'distribution'" @error="showError" />
      <StatsTab       v-if="tab === 'stats'"        :models="models" :conditions="conditions" @error="showError" />
    </main>

    <div v-if="toast" class="toast">
      <span>{{ toast }}</span>
      <button @click="clearToast">Dismiss</button>
    </div>
  </template>
</template>
