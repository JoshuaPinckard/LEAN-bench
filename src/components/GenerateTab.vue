<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '../api.js'
import ResultCard from './ResultCard.vue'
import CallDetailsModal from './CallDetailsModal.vue'
import PromptModal from './PromptModal.vue'

const props = defineProps({
  models:     { type: Array, required: true },
  conditions: { type: Array, required: true },
})
const emit = defineEmits(['error'])

// --- prompt source ----------------------------------------------------
const promptMode = ref('adhoc')        // 'adhoc' | 'saved'
const savedPromptId = ref('')
const promptText = ref('')
const savedPrompts = ref([])

async function loadSavedPrompts() {
  try {
    const data = await api.listPrompts({ limit: 500 })
    savedPrompts.value = data.prompts
  } catch (e) {
    emit('error', e.message)
  }
}
onMounted(loadSavedPrompts)

watch(savedPromptId, async (id) => {
  if (!id) { promptText.value = ''; return }
  try {
    const p = await api.getPrompt(id)
    promptText.value = p.reformulated_text
  } catch (e) {
    emit('error', e.message)
  }
})

watch(promptMode, (m) => {
  if (m === 'adhoc') savedPromptId.value = ''
})

// --- selections -------------------------------------------------------
const selectedModels = ref(new Set())
const selectedConds  = ref(new Set())

watch(() => props.conditions, (cs) => {
  // default: all four conditions checked per spec §5.2.D
  if (selectedConds.value.size === 0 && cs.length) {
    cs.forEach(c => selectedConds.value.add(c.id))
  }
}, { immediate: true })

// NOTE: Vue 3 auto-unwraps refs in templates, so passing `selectedModels` to a
// generic helper hands it the inner Set, not the ref — `set.value = ...` then
// silently no-ops. Use dedicated functions that close over the refs directly.
function toggleModel(key) {
  const s = new Set(selectedModels.value)
  s.has(key) ? s.delete(key) : s.add(key)
  selectedModels.value = s
}
function toggleCond(key) {
  const s = new Set(selectedConds.value)
  s.has(key) ? s.delete(key) : s.add(key)
  selectedConds.value = s
}
function selectAllModels()  { selectedModels.value = new Set(props.models.map(m => m.friendly_name)) }
function selectNoneModels() { selectedModels.value = new Set() }
function selectAllConds()   { selectedConds.value = new Set(props.conditions.map(c => c.id)) }
function selectNoneConds()  { selectedConds.value = new Set() }

const passK = ref(false)

const submitCount = computed(() => {
  const m = selectedModels.value.size
  const c = selectedConds.value.size
  return m * c * (passK.value ? 4 : 1)
})

const canSubmit = computed(() => {
  return promptText.value.trim() && selectedModels.value.size > 0 && selectedConds.value.size > 0
})

// --- generate ---------------------------------------------------------
const sending = ref(false)
const results = ref([])

async function send() {
  if (!canSubmit.value || sending.value) return
  sending.value = true
  results.value = []
  try {
    const data = await api.generate({
      prompt_id:   savedPromptId.value || null,
      prompt_text: promptText.value,
      models:      [...selectedModels.value],
      conditions:  [...selectedConds.value],
      attempts:    passK.value ? 4 : 1,
    })
    results.value = data.results
  } catch (e) {
    emit('error', e.message)
  } finally {
    sending.value = false
  }
}

// --- group results by condition for display --------------------------
const resultsByCondition = computed(() => {
  const out = {}
  for (const r of results.value) {
    if (!out[r.condition]) out[r.condition] = []
    out[r.condition].push(r)
  }
  return out
})

const providerOf = computed(() => {
  const m = {}
  for (const mod of props.models) m[mod.friendly_name] = mod.provider
  return m
})

const conditionMeta = computed(() => {
  const m = {}
  for (const c of props.conditions) m[c.id] = c
  return m
})

// --- save-to-library modal --------------------------------------------
const detailCallId = ref(null)

// --- save adhoc prompt to library -------------------------------------
const showSaveBtn = computed(() => promptMode.value === 'adhoc' && promptText.value.trim().length > 0)
const saveModalOpen = ref(false)

async function onPromptSaved(saved) {
  saveModalOpen.value = false
  await loadSavedPrompts()
  promptMode.value = 'saved'
  savedPromptId.value = saved.prompt_id
}
</script>

<template>
  <div class="generate-grid">
    <!-- LEFT: input panel ============================================ -->
    <aside class="input-panel">

      <!-- A. Prompt selector -->
      <section class="input-section">
        <div class="header">
          <h3>Prompt</h3>
          <span v-if="showSaveBtn" class="toggle" @click="saveModalOpen = true">+ Save to library</span>
        </div>
        <select v-model="promptMode" style="margin-bottom: 8px;">
          <option value="adhoc">New ad-hoc prompt</option>
          <option value="saved">From library…</option>
        </select>
        <select v-if="promptMode === 'saved'" v-model="savedPromptId">
          <option value="">— select —</option>
          <option v-for="p in savedPrompts" :key="p.prompt_id" :value="p.prompt_id">
            {{ p.prompt_id }} — {{ (p.reformulated_text || '').slice(0, 60) }}
          </option>
        </select>
      </section>

      <!-- B. Prompt textarea -->
      <section class="input-section">
        <textarea
          v-model="promptText"
          rows="8"
          placeholder="Write a LEAN algorithm that..."
          :readonly="promptMode === 'saved'"
          :style="promptMode === 'saved' ? 'background: var(--bg-chrome); color: var(--text-muted);' : ''"
        ></textarea>
      </section>

      <!-- C. Models -->
      <section class="input-section">
        <div class="header">
          <h3>Models</h3>
          <span class="toggle"
                @click="selectedModels.size === models.length ? selectNoneModels() : selectAllModels()">
            {{ selectedModels.size === models.length ? 'Deselect all' : 'Select all' }}
          </span>
        </div>
        <div v-for="m in models" :key="m.friendly_name" class="checkbox-row">
          <input type="checkbox" :id="'m-' + m.friendly_name"
                 :checked="selectedModels.has(m.friendly_name)"
                 @change="toggleModel(m.friendly_name)" />
          <label :for="'m-' + m.friendly_name" class="name">{{ m.friendly_name }}</label>
          <span class="badge" :class="m.provider">{{ m.provider }}</span>
        </div>
      </section>

      <!-- D. Conditions -->
      <section class="input-section">
        <div class="header">
          <h3>Conditions</h3>
          <span class="toggle"
                @click="selectedConds.size === conditions.length ? selectNoneConds() : selectAllConds()">
            {{ selectedConds.size === conditions.length ? 'Deselect all' : 'Select all' }}
          </span>
        </div>
        <div v-for="c in conditions" :key="c.id" class="checkbox-row" :title="c.semantics">
          <input type="checkbox" :id="'c-' + c.id"
                 :checked="selectedConds.has(c.id)"
                 @change="toggleCond(c.id)" />
          <label :for="'c-' + c.id" class="name">{{ c.id }}</label>
          <span class="desc">{{ c.display_name }}</span>
        </div>
      </section>

      <!-- E. Pass^4 toggle -->
      <section class="input-section">
        <label class="toggle-switch">
          <input type="checkbox" v-model="passK" />
          Pass^4 mode (run 4 times for variance)
          <span class="info-icon" title="Submits the same prompt to each (model, condition) cell 4 times to measure reliability. Multiplies cost by 4. Use only for the variance ablation study.">i</span>
        </label>
      </section>

      <!-- F. Submit -->
      <button @click="send" :disabled="!canSubmit || sending" style="width: 100%;">
        <span v-if="sending"><span class="spinner"></span> Running {{ submitCount }} call{{ submitCount === 1 ? '' : 's' }}…</span>
        <span v-else>Generate ({{ submitCount }} call{{ submitCount === 1 ? '' : 's' }})</span>
      </button>
    </aside>

    <!-- RIGHT: results =============================================== -->
    <section class="results-panel">
      <div v-if="!results.length && !sending" class="results-empty">
        Submit a prompt to see results.
      </div>
      <div v-else>
        <div v-for="cond in conditions.filter(c => resultsByCondition[c.id])" :key="cond.id" class="condition-row">
          <div class="row-header">
            {{ cond.id }} <span class="label">— {{ cond.display_name }}</span>
          </div>
          <div class="cards-grid">
            <ResultCard
              v-for="r in resultsByCondition[cond.id]"
              :key="r.call_id"
              :result="r"
              :condition="conditionMeta[cond.id]"
              :provider="providerOf[r.model]"
              @view-details="detailCallId = $event"
            />
          </div>
        </div>
      </div>
    </section>

    <CallDetailsModal :call-id="detailCallId" @close="detailCallId = null" />
    <PromptModal v-if="saveModalOpen" :seed-text="promptText" @close="saveModalOpen = false" @saved="onPromptSaved" />
  </div>
</template>
