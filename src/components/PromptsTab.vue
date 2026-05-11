<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '../api.js'
import PromptModal from './PromptModal.vue'

const emit = defineEmits(['error'])

const prompts = ref([])
const total = ref(0)
const search = ref('')
const offset = ref(0)
const limit = 50
const sortKey = ref('prompt_id')
const sortDesc = ref(false)

const editing = ref(null)        // null | 'new' | prompt_id
const confirmDelete = ref(null)  // null | { prompt_id, text }

async function load() {
  try {
    const data = await api.listPrompts({ search: search.value || undefined, limit, offset: offset.value })
    prompts.value = data.prompts
    total.value = data.total
  } catch (e) {
    emit('error', e.message)
  }
}

onMounted(load)

watch(search, () => { offset.value = 0; load() })

const sorted = computed(() => {
  const key = sortKey.value
  const sign = sortDesc.value ? -1 : 1
  return [...prompts.value].sort((a, b) => {
    const av = a[key] ?? ''
    const bv = b[key] ?? ''
    return av < bv ? -sign : av > bv ? sign : 0
  })
})

function setSort(k) {
  if (sortKey.value === k) sortDesc.value = !sortDesc.value
  else { sortKey.value = k; sortDesc.value = false }
}

function previewText(t) {
  if (!t) return ''
  return t.length > 80 ? t.slice(0, 80) + '…' : t
}
function dateOnly(iso) { return iso ? iso.split('T')[0] : '' }

async function doDelete() {
  if (!confirmDelete.value) return
  try {
    await api.deletePrompt(confirmDelete.value.prompt_id)
    confirmDelete.value = null
    await load()
  } catch (e) {
    emit('error', e.message)
  }
}

function onSaved() { editing.value = null; load() }

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit)))
const currentPage = computed(() => Math.floor(offset.value / limit) + 1)
function gotoPage(p) {
  offset.value = (p - 1) * limit
  load()
}
</script>

<template>
  <div>
    <div class="toolbar">
      <input type="text" v-model="search" placeholder="Search prompt text…" />
      <button @click="editing = 'new'">+ New Prompt</button>
    </div>

    <table class="data">
      <thead>
        <tr>
          <th @click="setSort('prompt_id')">prompt_id</th>
          <th @click="setSort('difficulty')">difficulty</th>
          <th @click="setSort('strategy_type')">strategy</th>
          <th>text</th>
          <th>tickers</th>
          <th @click="setSort('created_at')">created</th>
          <th class="actions"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="p in sorted" :key="p.prompt_id">
          <td class="mono">{{ p.prompt_id }}</td>
          <td><span class="pill" :class="p.difficulty">{{ p.difficulty }}</span></td>
          <td>{{ p.strategy_type || '—' }}</td>
          <td class="text-preview">{{ previewText(p.reformulated_text) }}</td>
          <td class="mono" style="font-size: 12px;">{{ (p.tickers || []).join(', ') }}</td>
          <td class="mono" style="font-size: 12px;">{{ dateOnly(p.created_at) }}</td>
          <td class="actions">
            <button class="icon" @click="editing = p.prompt_id" title="Edit">✎</button>
            <button class="icon" @click="confirmDelete = p" title="Delete">🗑</button>
          </td>
        </tr>
        <tr v-if="!sorted.length">
          <td colspan="7" style="text-align: center; padding: 32px; color: var(--text-muted);">
            No prompts in the library yet. Click "+ New Prompt" to add one.
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="totalPages > 1" class="pagination">
      <button class="secondary" :disabled="currentPage === 1" @click="gotoPage(currentPage - 1)">← Prev</button>
      <span style="padding: 6px 12px;">Page {{ currentPage }} of {{ totalPages }} ({{ total }} prompts)</span>
      <button class="secondary" :disabled="currentPage === totalPages" @click="gotoPage(currentPage + 1)">Next →</button>
    </div>

    <PromptModal v-if="editing"
                 :prompt-id="editing === 'new' ? null : editing"
                 @close="editing = null"
                 @saved="onSaved" />

    <div v-if="confirmDelete" class="modal-backdrop" @click.self="confirmDelete = null">
      <div class="modal" style="width: 480px;">
        <div class="modal-header">
          <h2>Delete prompt?</h2>
          <button class="icon" @click="confirmDelete = null" style="font-size: 18px;">✕</button>
        </div>
        <div class="modal-body">
          <p>Delete prompt <code>{{ confirmDelete.prompt_id }}</code>? This will also delete all associated calls. This cannot be undone.</p>
        </div>
        <div class="modal-footer">
          <button class="secondary" @click="confirmDelete = null">Cancel</button>
          <button class="danger" @click="doDelete">Delete</button>
        </div>
      </div>
    </div>
  </div>
</template>
