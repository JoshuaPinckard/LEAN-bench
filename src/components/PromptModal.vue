<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  promptId: { type: String, default: null },
  seedText: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved'])

const STRATEGY_TYPES   = ['trend_following', 'mean_reversion', 'momentum', 'options', 'pairs_trading', 'arbitrage', 'portfolio_construction', 'market_making', 'risk_parity', 'other']
const SECURITIES_TYPES = ['equity', 'forex', 'crypto', 'future', 'option', 'cfd', 'mixed']
const UNIVERSE_TYPES   = ['manual', 'dynamic_coarse', 'dynamic_coarse_fine', 'etf_constituents', 'option_chain']
const RESOLUTIONS      = ['tick', 'second', 'minute', 'hour', 'daily']
const ORDER_TYPES      = ['market', 'limit', 'stop', 'stop_limit']
const SOURCES          = ['original', 'quantconnect_forum', 'qc_docs_example', 'textbook', 'paper_reference', 'other']
const FAILURE_MODES    = [
  'indicator_initialization', 'warmup_handling', 'universe_selection',
  'scheduling_logic', 'order_execution', 'position_sizing',
  'lookahead_bias', 'resolution_mismatch', 'api_hallucination',
  'state_management', 'option_contract_selection', 'rolling_window_logic',
  'brokerage_constraints', 'risk_management', 'data_alignment',
]
const NOVELTY_LEVELS = [
  { value: 'canonical',          label: 'canonical',          desc: 'Classic well-known strategy (e.g. SMA crossover) — likely memorized' },
  { value: 'modified_canonical', label: 'modified_canonical', desc: 'Known idea with custom constraints or parameters' },
  { value: 'original_novel',     label: 'original_novel',     desc: 'Genuinely new construction by curator' },
  { value: 'post_cutoff_reference', label: 'post_cutoff_reference', desc: 'Uses new LEAN API, recent market event, or post-Dec 2025 concept' },
]

const form = reactive({
  text: '',
  difficulty: 'medium',
  strategy_type: 'trend_following',
  qc_securities_type: 'equity',
  qc_universe_type: 'manual',
  qc_data_resolution: 'daily',
  tickers: [],
  start_date: '2020-01-01',
  end_date: '2024-12-31',
  expected_indicators: [],        // list of {name, params}
  expected_order_types: [],
  trades_expected: true,
  primary_failure_mode: '',
  contains_behavioral_ambiguity: false,
  novelty_level: 'original_novel',
  source: 'original',
  source_url: '',
  curator_notes: '',
  leak_audit_status: 'clean',
})

const tickerDraft    = ref('')
const indicatorDraft = ref('')
const saving         = ref(false)
const apiError       = ref(null)

function parseIndicator(raw) {
  const s = raw.trim()
  if (!s) return null
  const m = s.match(/^([A-Za-z_][\w]*)\s*\(\s*([^)]*)\s*\)\s*$/)
  if (!m) return { name: s, params: [] }
  const params = m[2].split(',').map(p => {
    const t = p.trim()
    if (!t) return null
    const n = Number(t)
    return Number.isFinite(n) ? n : t
  }).filter(p => p !== null)
  return { name: m[1], params }
}
function indicatorLabel(ind) {
  if (typeof ind === 'string') return ind
  return ind.params?.length ? `${ind.name}(${ind.params.join(',')})` : ind.name
}

onMounted(async () => {
  if (props.promptId) {
    try {
      const p = await api.getPrompt(props.promptId)
      Object.assign(form, {
        text: p.reformulated_text || '',
        difficulty: p.difficulty || 'medium',
        strategy_type: p.strategy_type || 'trend_following',
        qc_securities_type: p.qc_securities_type || 'equity',
        qc_universe_type: p.qc_universe_type || 'manual',
        qc_data_resolution: p.qc_data_resolution || 'daily',
        tickers: p.tickers || [],
        start_date: p.start_date || '2020-01-01',
        end_date: p.end_date || '2024-12-31',
        expected_indicators: p.expected_indicators || [],
        expected_order_types: p.expected_order_types || [],
        trades_expected: !!p.trades_expected,
        primary_failure_mode: p.primary_failure_mode || '',
        contains_behavioral_ambiguity: !!p.contains_behavioral_ambiguity,
        novelty_level: p.novelty_level || 'original_novel',
        source: p.source || 'original',
        source_url: p.original_url || '',
        curator_notes: p.leak_audit_notes || '',
        leak_audit_status: p.leak_audit_status || 'clean',
      })
    } catch (e) { apiError.value = e.message }
  } else if (props.seedText) {
    form.text = props.seedText
  }
})

function addTicker() {
  const v = tickerDraft.value.trim().toUpperCase()
  if (!v) return
  if (!form.tickers.includes(v)) form.tickers.push(v)
  tickerDraft.value = ''
}
function removeTicker(i) { form.tickers.splice(i, 1) }

function addIndicator() {
  const parsed = parseIndicator(indicatorDraft.value)
  if (!parsed) return
  const label = indicatorLabel(parsed)
  if (form.expected_indicators.some(x => indicatorLabel(x) === label)) { indicatorDraft.value = ''; return }
  form.expected_indicators.push(parsed)
  indicatorDraft.value = ''
}
function removeIndicator(i) { form.expected_indicators.splice(i, 1) }

function toggleOrderType(t) {
  const i = form.expected_order_types.indexOf(t)
  if (i >= 0) form.expected_order_types.splice(i, 1)
  else form.expected_order_types.push(t)
}

const errors = computed(() => {
  const e = {}
  const text = form.text.trim()
  if (text.length < 20)   e.text = 'Prompt text must be at least 20 characters.'
  if (text.length > 2000) e.text = 'Prompt text must be at most 2000 characters.'
  if (!form.difficulty)         e.difficulty = 'Required.'
  if (!form.strategy_type)      e.strategy_type = 'Required.'
  if (!form.qc_securities_type) e.qc_securities_type = 'Required.'
  if (!form.qc_universe_type)   e.qc_universe_type = 'Required.'
  if (!form.qc_data_resolution) e.qc_data_resolution = 'Required.'
  if (!form.tickers.length) e.tickers = 'Add at least one ticker.'
  if (!form.start_date) e.start_date = 'Required.'
  if (!form.end_date)   e.end_date = 'Required.'
  if (form.start_date && form.end_date && form.end_date <= form.start_date)
    e.end_date = 'End date must be after start date.'
  if (form.trades_expected && !form.expected_order_types.length)
    e.expected_order_types = 'Select at least one order type when trades are expected.'
  if (!form.primary_failure_mode) e.primary_failure_mode = 'Required — which failure mode does this prompt test?'
  if (!form.novelty_level) e.novelty_level = 'Required.'
  if (!form.source) e.source = 'Required.'
  if (form.source !== 'original' && !form.source_url.trim())
    e.source_url = 'Required when source is not "original".'
  if (form.curator_notes.trim().length < 30) e.curator_notes = 'At least 30 characters required.'
  return e
})

const isValid    = computed(() => Object.keys(errors.value).length === 0)
const charCount  = computed(() => form.text.trim().length)
const notesCount = computed(() => form.curator_notes.trim().length)

async function save(addAnother = false) {
  if (!isValid.value) return
  saving.value = true
  apiError.value = null
  const payload = { ...form }
  if (form.source === 'original') payload.source_url = null
  try {
    let saved
    if (props.promptId) saved = await api.updatePrompt(props.promptId, payload)
    else                saved = await api.createPrompt(payload)
    emit('saved', saved)
    if (addAnother) {
      Object.assign(form, {
        text: '', tickers: [], expected_indicators: [], expected_order_types: [],
        trades_expected: true, contains_behavioral_ambiguity: false,
        primary_failure_mode: '', source_url: '', curator_notes: '',
      })
      tickerDraft.value = ''
      indicatorDraft.value = ''
    }
  } catch (e) {
    apiError.value = e.message
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
        <button class="icon" @click="$emit('close')" style="font-size:18px;">✕</button>
      </div>

      <div class="modal-body">
        <div v-if="apiError" class="error-box">{{ apiError }}</div>

        <!-- 1. Prompt text -->
        <div class="form-grid">
          <div class="form-row full">
            <label>Prompt text *</label>
            <textarea v-model="form.text" rows="8" :class="{ invalid: errors.text }"
                      placeholder="Write a LEAN algorithm that..."
                      style="font-family: monospace;"></textarea>
            <div class="helper">
              <span :class="{ error: errors.text }">{{ errors.text || `${charCount} / 2000` }}</span>
            </div>
          </div>
        </div>

        <!-- 2. Categorization -->
        <h4 class="section-title">Categorization</h4>
        <div class="form-grid">
          <div class="form-row">
            <label>Difficulty *</label>
            <div style="display:flex;gap:12px;">
              <label v-for="d in ['easy','medium','hard']" :key="d" style="font-weight:normal;">
                <input type="radio" v-model="form.difficulty" :value="d" /> {{ d }}
              </label>
            </div>
          </div>
          <div class="form-row">
            <label>Strategy type *</label>
            <select v-model="form.strategy_type">
              <option v-for="s in STRATEGY_TYPES" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
        </div>

        <!-- 3. LEAN config -->
        <h4 class="section-title">LEAN configuration</h4>
        <div class="form-grid">
          <div class="form-row">
            <label>QC securities type *</label>
            <select v-model="form.qc_securities_type">
              <option v-for="s in SECURITIES_TYPES" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
          <div class="form-row">
            <label>QC universe type *</label>
            <select v-model="form.qc_universe_type">
              <option v-for="u in UNIVERSE_TYPES" :key="u" :value="u">{{ u }}</option>
            </select>
          </div>
          <div class="form-row">
            <label>QC data resolution *</label>
            <select v-model="form.qc_data_resolution">
              <option v-for="r in RESOLUTIONS" :key="r" :value="r">{{ r }}</option>
            </select>
          </div>
        </div>

        <!-- 4. Universe and time window -->
        <h4 class="section-title">Universe and time window</h4>
        <div class="form-grid">
          <div class="form-row full">
            <label>Tickers * (type ticker, press Enter)</label>
            <div class="chip-input" :class="{ invalid: errors.tickers }">
              <span v-for="(t, i) in form.tickers" :key="t" class="chip">
                {{ t }} <button @click="removeTicker(i)">×</button>
              </span>
              <input type="text" v-model="tickerDraft"
                     @keydown.enter.prevent="addTicker" @blur="addTicker"
                     placeholder="SPY" />
            </div>
            <div v-if="errors.tickers" class="helper error">{{ errors.tickers }}</div>
          </div>
          <div class="form-row">
            <label>Start date *</label>
            <input type="date" v-model="form.start_date" />
            <div v-if="errors.start_date" class="helper error">{{ errors.start_date }}</div>
          </div>
          <div class="form-row">
            <label>End date *</label>
            <input type="date" v-model="form.end_date" />
            <div v-if="errors.end_date" class="helper error">{{ errors.end_date }}</div>
          </div>
        </div>

        <!-- 5. Expected behavior -->
        <h4 class="section-title">Expected behavior</h4>
        <div class="form-grid">
          <div class="form-row full">
            <label>Expected indicators (type as <code>NAME(params)</code>, press Enter)</label>
            <div class="chip-input">
              <span v-for="(ind, i) in form.expected_indicators" :key="i" class="chip">
                {{ indicatorLabel(ind) }} <button @click="removeIndicator(i)">×</button>
              </span>
              <input type="text" v-model="indicatorDraft"
                     @keydown.enter.prevent="addIndicator" @blur="addIndicator"
                     placeholder="SMA(50)" />
            </div>
            <div class="helper">e.g., SMA(50), RSI(14), MACD(12,26,9), BB(20,2), ATR(14)</div>
          </div>
          <div class="form-row full">
            <label>Expected order types <span v-if="form.trades_expected">*</span></label>
            <div style="display:flex;gap:16px;flex-wrap:wrap;">
              <label v-for="t in ORDER_TYPES" :key="t" style="font-weight:normal;">
                <input type="checkbox" :checked="form.expected_order_types.includes(t)" @change="toggleOrderType(t)" />
                {{ t }}
              </label>
            </div>
            <div v-if="errors.expected_order_types" class="helper error">{{ errors.expected_order_types }}</div>
          </div>
          <div class="form-row">
            <label>Trades expected</label>
            <label class="toggle-switch" style="font-weight:normal;"
                   title="Should a correctly implemented strategy place at least one trade in the backtest window?">
              <input type="checkbox" v-model="form.trades_expected" />
              {{ form.trades_expected ? 'yes' : 'no (intentional zero-trade strategy)' }}
            </label>
          </div>
        </div>

        <!-- 6. Evaluation metadata -->
        <h4 class="section-title">Evaluation metadata</h4>
        <div class="form-grid">
          <div class="form-row">
            <label>Primary failure mode *</label>
            <select v-model="form.primary_failure_mode" :class="{ invalid: errors.primary_failure_mode }">
              <option value="">— select —</option>
              <option v-for="f in FAILURE_MODES" :key="f" :value="f">{{ f }}</option>
            </select>
            <div class="helper" :class="{ error: errors.primary_failure_mode }">
              {{ errors.primary_failure_mode || 'Which failure mode is this prompt designed to surface?' }}
            </div>
          </div>
          <div class="form-row">
            <label>Novelty level *</label>
            <select v-model="form.novelty_level" :class="{ invalid: errors.novelty_level }">
              <option v-for="n in NOVELTY_LEVELS" :key="n.value" :value="n.value">{{ n.label }}</option>
            </select>
            <div class="helper">{{ NOVELTY_LEVELS.find(n => n.value === form.novelty_level)?.desc }}</div>
          </div>
          <div class="form-row full">
            <label>Behavioral ambiguity</label>
            <label class="toggle-switch" style="font-weight:normal;"
                   title="Check if the prompt admits multiple meaningfully different correct implementations, or if the entry/exit logic is not fully specified.">
              <input type="checkbox" v-model="form.contains_behavioral_ambiguity" />
              {{ form.contains_behavioral_ambiguity ? 'yes — prompt has unresolved behavioral ambiguity' : 'no — implementation is well-specified' }}
            </label>
          </div>
        </div>

        <!-- 7. Provenance -->
        <h4 class="section-title">Provenance</h4>
        <div class="form-grid">
          <div class="form-row">
            <label>Source *</label>
            <select v-model="form.source">
              <option v-for="s in SOURCES" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
          <div class="form-row" v-if="form.source !== 'original'">
            <label>Source URL *</label>
            <input type="text" v-model="form.source_url" :class="{ invalid: errors.source_url }"
                   placeholder="https://..." />
            <div class="helper" :class="{ error: errors.source_url }">
              {{ errors.source_url || 'Link to source material (forum post, docs page, paper)' }}
            </div>
          </div>
        </div>

        <!-- 8. Documentation -->
        <h4 class="section-title">Documentation</h4>
        <div class="form-grid">
          <div class="form-row full">
            <label>Curator notes *</label>
            <textarea v-model="form.curator_notes" rows="4" :class="{ invalid: errors.curator_notes }"
                      placeholder="What failure mode does this prompt test? Why include it?&#10;Known ambiguities or edge cases?&#10;&#10;Example: &quot;Tests SetWarmUp(200) usage. Common failure: models trade on uninitialized indicators. Ambiguity: 'goes LONG' doesn't specify exit — judge treats hold-forever as acceptable.&quot;"></textarea>
            <div class="helper">
              <span :class="{ error: errors.curator_notes }">{{ errors.curator_notes || `${notesCount} / 30 min` }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="modal-footer">
        <button class="secondary" @click="$emit('close')">Cancel</button>
        <button v-if="!promptId" class="secondary" @click="save(true)" :disabled="!isValid || saving">Save and add another</button>
        <button @click="save(false)" :disabled="!isValid || saving">{{ saving ? 'Saving…' : 'Save' }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.section-title {
  margin: 18px 0 8px;
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted, #888);
  border-bottom: 1px solid var(--border, #e5e5e5);
  padding-bottom: 4px;
}
.helper { font-size: 12px; color: var(--text-muted, #888); margin-top: 4px; }
.helper.error { color: #d33; }
.helper code { background: var(--bg-chrome, #f0f0f0); padding: 1px 4px; border-radius: 3px; font-size: 11px; }
</style>
