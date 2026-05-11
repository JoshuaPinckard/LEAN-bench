<script setup>
import { ref, reactive, watch, onMounted } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  promptId: { type: String, default: null },   // null = create
  seedText: { type: String, default: '' },     // pre-fill text when saving an ad-hoc prompt
})
const emit = defineEmits(['close', 'saved'])

const STRATEGY_TYPES   = ['trend_following', 'mean_reversion', 'momentum', 'arbitrage', 'market_making', 'portfolio_construction', 'options', 'risk_parity', 'other']
const SECURITIES_TYPES = ['equity', 'forex', 'crypto', 'future', 'option', 'cfd', 'mixed']
const RESOLUTIONS      = ['tick', 'second', 'minute', 'hour', 'daily']
const ORDER_TYPES      = ['market', 'limit', 'stop', 'stop_limit']

const form = reactive({
  text: '',
  difficulty: 'medium',
  strategy_type: 'trend_following',
  qc_securities_type: 'equity',
  qc_data_resolution: 'daily',
  tickers: [],
  start_date: '2020-01-01',
  end_date: '2024-12-31',
  expected_indicators: [],
  expected_order_types: [],
  trades_expected: true,
  curator_notes: '',
  source: 'original',
  is_post_cutoff: false,
  leak_audit_status: 'clean',
})

const errors = reactive({})
const tickerDraft = ref('')
const indicatorDraft = ref('')
const saving = ref(false)
const error = ref(null)

onMounted(async () => {
  if (props.promptId) {
    try {
      const p = await api.getPrompt(props.promptId)
      Object.assign(form, {
        text: p.reformulated_text,
        difficulty: p.difficulty || 'medium',
        strategy_type: p.strategy_type || 'trend_following',
        qc_securities_type: p.qc_securities_type || 'equity',
        qc_data_resolution: p.qc_data_resolution || 'daily',
        tickers: p.tickers || [],
        start_date: p.start_date || '2020-01-01',
        end_date: p.end_date || '2024-12-31',
        expected_indicators: p.expected_indicators || [],
        expected_order_types: p.expected_order_types || [],
        trades_expected: !!p.trades_expected,
        curator_notes: p.leak_audit_notes || '',
        source: p.source || 'original',
        is_post_cutoff: !!p.is_post_cutoff,
        leak_audit_status: p.leak_audit_status || 'clean',
      })
    } catch (e) { error.value = e.message }
  } else if (props.seedText) {
    form.text = props.seedText
  }
})

function addChip(field, draftRef) {
  const v = draftRef.value.trim()
  if (!v) return
  if (!form[field].includes(v)) form[field].push(v)
  draftRef.value = ''
}
function removeChip(field, idx) {
  form[field].splice(idx, 1)
}

function toggleOrderType(t) {
  const i = form.expected_order_types.indexOf(t)
  if (i >= 0) form.expected_order_types.splice(i, 1)
  else form.expected_order_types.push(t)
}

function validate() {
  for (const k of Object.keys(errors)) delete errors[k]
  if (!form.text.trim())            errors.text = 'Prompt text is required.'
  if (!form.difficulty)             errors.difficulty = 'Pick a difficulty.'
  if (!form.strategy_type)          errors.strategy_type = 'Pick a strategy type.'
  if (!form.qc_securities_type)     errors.qc_securities_type = 'Pick a securities type.'
  if (!form.qc_data_resolution)     errors.qc_data_resolution = 'Pick a data resolution.'
  if (!form.tickers.length)         errors.tickers = 'Add at least one ticker.'
  if (!form.start_date)             errors.start_date = 'Required.'
  if (!form.end_date)               errors.end_date = 'Required.'
  return Object.keys(errors).length === 0
}

async function save(addAnother = false) {
  if (!validate()) return
  saving.value = true
  error.value = null
  try {
    let saved
    if (props.promptId) {
      saved = await api.updatePrompt(props.promptId, form)
    } else {
      saved = await api.createPrompt(form)
    }
    emit('saved', saved)
    if (addAnother) {
      // Reset for next entry
      Object.assign(form, {
        text: '', tickers: [], expected_indicators: [], expected_order_types: [],
        trades_expected: true, curator_notes: '',
      })
    }
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal">
      <div class="modal-header">
        <h2>{{ promptId ? 'Edit prompt ' + promptId : 'New prompt' }}</h2>
        <button class="icon" @click="$emit('close')" style="font-size: 18px;">✕</button>
      </div>

      <div class="modal-body">
        <div v-if="error" class="error-box">{{ error }}</div>

        <div class="form-grid">
          <div class="form-row full">
            <label>Prompt text *</label>
            <textarea v-model="form.text" rows="10" :class="{ invalid: errors.text }" placeholder="Describe the LEAN strategy in natural language. Do NOT paste code."></textarea>
            <div v-if="errors.text" class="helper error">{{ errors.text }}</div>
          </div>

          <div class="form-row">
            <label>Difficulty *</label>
            <div style="display: flex; gap: 12px;">
              <label v-for="d in ['easy', 'medium', 'hard']" :key="d" style="font-weight: normal;">
                <input type="radio" v-model="form.difficulty" :value="d" /> {{ d }}
              </label>
            </div>
          </div>

          <div class="form-row">
            <label>Strategy type *</label>
            <select v-model="form.strategy_type" :class="{ invalid: errors.strategy_type }">
              <option v-for="s in STRATEGY_TYPES" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>

          <div class="form-row">
            <label>QC securities type *</label>
            <select v-model="form.qc_securities_type">
              <option v-for="s in SECURITIES_TYPES" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>

          <div class="form-row">
            <label>QC data resolution *</label>
            <select v-model="form.qc_data_resolution">
              <option v-for="r in RESOLUTIONS" :key="r" :value="r">{{ r }}</option>
            </select>
          </div>

          <div class="form-row full">
            <label>Tickers * (type and press Enter)</label>
            <div class="chip-input" :class="{ invalid: errors.tickers }">
              <span v-for="(t, i) in form.tickers" :key="t" class="chip">
                {{ t }} <button @click="removeChip('tickers', i)">×</button>
              </span>
              <input type="text" v-model="tickerDraft"
                     @keydown.enter.prevent="addChip('tickers', tickerDraft)"
                     placeholder="SPY" />
            </div>
            <div v-if="errors.tickers" class="helper error">{{ errors.tickers }}</div>
          </div>

          <div class="form-row">
            <label>Start date *</label>
            <input type="date" v-model="form.start_date" :class="{ invalid: errors.start_date }" />
          </div>

          <div class="form-row">
            <label>End date *</label>
            <input type="date" v-model="form.end_date" :class="{ invalid: errors.end_date }" />
          </div>

          <div class="form-row full">
            <label>Expected indicators</label>
            <div class="chip-input">
              <span v-for="(t, i) in form.expected_indicators" :key="t" class="chip">
                {{ t }} <button @click="removeChip('expected_indicators', i)">×</button>
              </span>
              <input type="text" v-model="indicatorDraft"
                     @keydown.enter.prevent="addChip('expected_indicators', indicatorDraft)"
                     placeholder="RSI(14)" />
            </div>
          </div>

          <div class="form-row full">
            <label>Expected order types</label>
            <div style="display: flex; gap: 16px;">
              <label v-for="t in ORDER_TYPES" :key="t" style="font-weight: normal;">
                <input type="checkbox" :checked="form.expected_order_types.includes(t)" @change="toggleOrderType(t)" />
                {{ t }}
              </label>
            </div>
          </div>

          <div class="form-row">
            <label>Trades expected</label>
            <label class="toggle-switch" style="font-weight: normal;">
              <input type="checkbox" v-model="form.trades_expected" />
              {{ form.trades_expected ? 'yes' : 'no (intentional zero-trade strategy)' }}
            </label>
          </div>

          <div class="form-row full">
            <label>Curator notes</label>
            <textarea v-model="form.curator_notes" rows="3" placeholder="Why is this prompt in the benchmark? Any caveats?"></textarea>
          </div>
        </div>
      </div>

      <div class="modal-footer">
        <button class="secondary" @click="$emit('close')">Cancel</button>
        <button v-if="!promptId" class="secondary" @click="save(true)" :disabled="saving">Save and add another</button>
        <button @click="save(false)" :disabled="saving">{{ saving ? 'Saving…' : 'Save' }}</button>
      </div>
    </div>
  </div>
</template>
