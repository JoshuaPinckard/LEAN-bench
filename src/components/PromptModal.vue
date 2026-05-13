<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  promptId: { type: String, default: null },
  seedText: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved'])

const STRATEGY_TYPES = [
  { value: 'directional',    desc: 'Trend following and momentum' },
  { value: 'mean_reversion', desc: 'Strategies that bet on return to mean' },
  { value: 'derivatives',    desc: 'Options and volatility strategies' },
  { value: 'portfolio',      desc: 'Portfolio construction and risk parity' },
  { value: 'execution',      desc: 'Market making and execution' },
  { value: 'relative_value', desc: 'Arbitrage and pairs trading' },
  { value: 'other',          desc: '' },
]
const SECURITIES_TYPES  = ['equity', 'option', 'multi_asset']
const SECURITIES_DETAIL = ['equity', 'forex', 'crypto', 'future', 'option', 'cfd', 'mixed']
const RESOLUTIONS = [
  { value: 'daily',          desc: 'End-of-day bars' },
  { value: 'intraday',       desc: 'Minute or hour bars' },
  { value: 'high_frequency', desc: 'Tick or second data' },
]
const EVAL_MODES = [
  { value: 'trade_required',           desc: 'At least one trade must be placed' },
  { value: 'signal_required',          desc: 'Signal must be generated even if no fill' },
  { value: 'code_only',                desc: 'Compile and import check only; no backtest required' },
  { value: 'metric_threshold_required',desc: 'Specific performance metric (e.g. Sharpe) must be met' },
]
const SOURCES = ['original', 'quantconnect_forum', 'qc_docs_example', 'textbook', 'paper_reference', 'other']

const IMPLEMENTATION_TYPES = [
  { value: 'lean_native',            desc: "Solvable using only LEAN's built-in indicators, methods, and data (self.SMA(), self.History(), etc.)" },
  { value: 'custom_implementation',  desc: 'Requires writing custom logic, math, or indicators not built into LEAN (e.g. Hurst exponent from scratch)' },
  { value: 'external_data_required', desc: "Requires data sources outside LEAN's default feed (alternative data, sentiment feeds, custom CSVs)" },
  { value: 'mixed',                  desc: 'Combines two or more of the above' },
]
const UNIVERSE_TYPES = [
  { value: 'single_asset',          desc: 'Strategy trades exactly one specified ticker' },
  { value: 'multi_asset_specific',  desc: 'Strategy trades a small, named list of tickers' },
  { value: 'index_components',      desc: 'Strategy trades the components of a known index' },
  { value: 'screened_universe',     desc: 'Strategy dynamically selects tickers based on criteria' },
  { value: 'custom_universe_logic', desc: 'Strategy requires custom universe selection logic beyond standard screens' },
]
const INDEX_OPTIONS = ['SP500', 'NASDAQ100', 'RUSSELL2000', 'DOW30', 'SP400_MIDCAP', 'RUSSELL1000', 'other']

const INDICATOR_SUGGESTIONS = [
  'SMA', 'EMA', 'WMA', 'DEMA', 'TEMA', 'VWAP',
  'RSI', 'MACD', 'Stochastic', 'ROC', 'CCI', 'Williams_R',
  'Bollinger', 'ATR', 'Keltner', 'Donchian', 'StdDev',
  'ADX', 'Aroon', 'Parabolic_SAR', 'Ichimoku',
  'OBV', 'MFI', 'AccumDist', 'ChaikinMF',
]

const FAILURE_MODE_OPTIONS = [
  { value: 'compilation_error',       desc: 'Code does not compile or has syntax errors' },
  { value: 'runtime_error',           desc: 'Code compiles but crashes during backtest' },
  { value: 'hallucinated_api',        desc: "Code references LEAN methods or classes that don't exist" },
  { value: 'no_trades_placed',        desc: 'Code runs cleanly but never trades' },
  { value: 'wrong_indicator',         desc: 'Uses an incorrect indicator or miscalculates one' },
  { value: 'wrong_universe',          desc: 'Trades the wrong assets or fails to select the intended universe' },
  { value: 'logic_error',             desc: "Trades occur but strategy logic doesn't match the prompt's intent" },
  { value: 'threshold_miss',          desc: 'All requirements met but performance threshold not achieved' },
  { value: 'incomplete_implementation', desc: 'Code stops short of fully implementing the prompt' },
  { value: 'none',                    desc: 'No failure; model succeeded' },
]

const COMPLEXITY_LABELS = { 1: '1 — easy', 2: '2 — medium', 3: '3 — hard' }
const API_LABELS = { 1: '1 — basic', 2: '2 — intermediate', 3: '3 — advanced' }
const STRICTNESS_LABELS = {
  0: '0 — unambiguous',
  1: '1 — mild (minor gaps)',
  2: '2 — broad (multiple valid implementations)',
  3: '3 — exclude (too ambiguous to evaluate)',
}

const form = reactive({
  text: '',
  strategy_type: 'directional',
  strategy_complexity: 2,
  api_complexity: 2,
  securities_type: 'equity',
  securities_type_detailed: '',
  resolution: 'daily',
  implementation_type: 'lean_native',
  indicators: [],
  universe_type: 'single_asset',
  universe_index: '',
  universe_index_other: '',
  tickers: [],
  start_date: '2020-01-01',
  end_date: '2024-12-31',
  evaluation_mode: 'trade_required',
  interpretation_strictness: 0,
  underspecification_notes: '',
  failure_mode: [],
  failure_notes: '',
  source: 'original',
  source_url: '',
  source_date: '',
  curator_notes: '',
  leak_audit_status: 'clean',
})

const tickerDraft     = ref('')
const indicatorDraft  = ref('')
const showDetailedSec = ref(false)
const saving          = ref(false)
const apiError        = ref(null)

// --- AI schema autofill ----------------------------------------------
const aiPopulating  = ref(false)
const aiError       = ref(null)
// Snapshot of the AI-suggested values right after a successful autofill.
// Used at save-time to compute curator_modified_fields. null = AI never ran.
const aiSnapshot    = ref(null)

const AI_TRACKED_FIELDS = [
  'strategy_type', 'strategy_complexity', 'api_complexity',
  'securities_type', 'securities_type_detailed', 'resolution',
  'implementation_type', 'indicators',
  'universe_type', 'universe_index', 'tickers',
  'start_date', 'end_date',
  'evaluation_mode', 'interpretation_strictness',
  'curator_notes',
]

const canAutofill = computed(() => form.text.trim().length >= 20 && !aiPopulating.value)

async function populateWithAi() {
  if (!canAutofill.value) return
  aiPopulating.value = true
  aiError.value = null
  try {
    const result = await api.schemaAutofill(form.text)
    // Apply suggestions to the form.
    for (const k of AI_TRACKED_FIELDS) {
      if (result[k] !== undefined && result[k] !== null) {
        form[k] = result[k]
      } else if (k === 'securities_type_detailed' || k === 'universe_index') {
        form[k] = ''
      }
    }
    if (form.securities_type_detailed) showDetailedSec.value = true
    // Snapshot for diffing on save.
    aiSnapshot.value = AI_TRACKED_FIELDS.reduce((acc, k) => {
      acc[k] = JSON.parse(JSON.stringify(form[k]))  // deep copy
      return acc
    }, {})
  } catch (e) {
    aiError.value = 'AI population failed, please fill in manually.'
    console.error('schema autofill error:', e)
  } finally {
    aiPopulating.value = false
  }
}

function computeModifiedFields() {
  if (!aiSnapshot.value) return []
  const modified = []
  for (const k of AI_TRACKED_FIELDS) {
    const a = JSON.stringify(aiSnapshot.value[k])
    const b = JSON.stringify(form[k])
    if (a !== b) modified.push(k)
  }
  return modified
}

const tickerVisible   = computed(() => ['single_asset', 'multi_asset_specific'].includes(form.universe_type))
const indexVisible    = computed(() => form.universe_type === 'index_components')

onMounted(async () => {
  if (props.promptId) {
    try {
      const p = await api.getPrompt(props.promptId)
      Object.assign(form, {
        text: p.reformulated_text || '',
        strategy_type: p.strategy_type || 'directional',
        strategy_complexity: p.strategy_complexity ?? 2,
        api_complexity: p.api_complexity ?? 2,
        securities_type: p.securities_type || 'equity',
        securities_type_detailed: p.securities_type_detailed || '',
        resolution: p.resolution || 'daily',
        implementation_type: p.implementation_type || 'lean_native',
        indicators: p.indicators || [],
        universe_type: p.universe_type || 'single_asset',
        universe_index: p.universe_index || '',
        universe_index_other: p.universe_index_other || '',
        tickers: p.tickers || [],
        start_date: p.start_date || '2020-01-01',
        end_date: p.end_date || '2024-12-31',
        evaluation_mode: p.evaluation_mode || 'trade_required',
        interpretation_strictness: p.interpretation_strictness ?? 0,
        underspecification_notes: p.underspecification_notes || '',
        failure_mode: p.failure_mode || [],
        failure_notes: p.failure_notes || '',
        source: p.source || 'original',
        source_url: p.original_url || '',
        source_date: p.source_date || '',
        curator_notes: p.leak_audit_notes || '',
        leak_audit_status: p.leak_audit_status || 'clean',
      })
      if (p.securities_type_detailed) showDetailedSec.value = true
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
  const v = indicatorDraft.value.trim()
  if (!v) return
  if (!form.indicators.includes(v)) form.indicators.push(v)
  indicatorDraft.value = ''
}
function removeIndicator(i) { form.indicators.splice(i, 1) }

function toggleFailureMode(v) {
  const i = form.failure_mode.indexOf(v)
  if (i >= 0) form.failure_mode.splice(i, 1)
  else form.failure_mode.push(v)
}

const errors = computed(() => {
  const e = {}
  const text = form.text.trim()
  if (text.length < 20)   e.text = 'At least 20 characters required.'
  if (text.length > 2000) e.text = 'At most 2000 characters.'
  if (!form.strategy_type)   e.strategy_type = 'Required.'
  if (![1,2,3].includes(form.strategy_complexity)) e.strategy_complexity = '1, 2, or 3 required.'
  if (![1,2,3].includes(form.api_complexity))      e.api_complexity = '1, 2, or 3 required.'
  if (!form.securities_type)    e.securities_type = 'Required.'
  if (!form.resolution)         e.resolution = 'Required.'
  if (!form.implementation_type) e.implementation_type = 'Required.'
  if (!form.universe_type)      e.universe_type = 'Required.'
  if (tickerVisible.value && !form.tickers.length)
    e.tickers = 'Add at least one ticker.'
  if (indexVisible.value && !form.universe_index)
    e.universe_index = 'Pick an index.'
  if (indexVisible.value && form.universe_index === 'other' && !form.universe_index_other.trim())
    e.universe_index_other = 'Specify the index.'
  if (!form.start_date)  e.start_date = 'Required.'
  if (!form.end_date)    e.end_date = 'Required.'
  if (form.start_date && form.end_date && form.end_date <= form.start_date)
    e.end_date = 'End date must be after start date.'
  if (!form.evaluation_mode) e.evaluation_mode = 'Required.'
  if (![0,1,2,3].includes(form.interpretation_strictness)) e.interpretation_strictness = '0–3 required.'
  if (!form.source) e.source = 'Required.'
  if (form.source !== 'original' && !form.source_url.trim())
    e.source_url = 'Required when source is not "original".'
  if (form.curator_notes.trim().length < 80)
    e.curator_notes = `At least 80 characters (${form.curator_notes.trim().length} so far).`
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
  if (!form.securities_type_detailed) payload.securities_type_detailed = null
  if (!form.underspecification_notes) payload.underspecification_notes = null
  if (!form.source_date) payload.source_date = null
  if (!form.failure_notes) payload.failure_notes = null
  // Drop tickers / index fields that don't apply to the chosen universe_type
  if (!tickerVisible.value) payload.tickers = []
  if (!indexVisible.value)  { payload.universe_index = null; payload.universe_index_other = null }
  if (form.universe_index !== 'other') payload.universe_index_other = null
  // Cast to int in case reactive coerced to string
  payload.strategy_complexity = parseInt(form.strategy_complexity)
  payload.api_complexity       = parseInt(form.api_complexity)
  payload.interpretation_strictness = parseInt(form.interpretation_strictness)
  // AI autofill telemetry
  payload.ai_prepopulated = aiSnapshot.value !== null
  payload.curator_modified_fields = computeModifiedFields()
  try {
    let saved
    if (props.promptId) saved = await api.updatePrompt(props.promptId, payload)
    else                saved = await api.createPrompt(payload)
    emit('saved', saved)
    if (addAnother) {
      Object.assign(form, {
        text: '', tickers: [], indicators: [],
        strategy_complexity: 2, api_complexity: 2,
        interpretation_strictness: 0, underspecification_notes: '',
        failure_mode: [], failure_notes: '',
        universe_index: '', universe_index_other: '',
        source_url: '', source_date: '', curator_notes: '',
      })
      tickerDraft.value = ''
      indicatorDraft.value = ''
      showDetailedSec.value = false
      aiSnapshot.value = null
      aiError.value = null
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
        <h2>{{ promptId ? 'Edit ' + promptId : 'New prompt' }}</h2>
        <button class="icon" @click="$emit('close')" style="font-size:18px;">✕</button>
      </div>

      <div class="modal-body">
        <div v-if="apiError" class="error-box">{{ apiError }}</div>

        <!-- AI autofill bar -->
        <div class="ai-autofill-bar">
          <button class="ai-autofill-btn"
                  :disabled="!canAutofill"
                  @click="populateWithAi"
                  :title="canAutofill ? 'Use Sonnet to suggest values for every field below' : 'Type at least 20 characters of prompt text first'">
            <span v-if="aiPopulating"><span class="spinner"></span> Populating…</span>
            <span v-else>✨ Populate Schema with AI</span>
          </button>
          <span v-if="aiSnapshot && !aiError && !aiPopulating" class="ai-hint">
            AI suggestions applied — feel free to edit any field
          </span>
        </div>
        <div v-if="aiError" class="error-box ai-error-box">{{ aiError }}</div>

        <!-- 1: Prompt text -->
        <div class="form-grid">
          <div class="form-row full">
            <label>Prompt text *</label>
            <textarea v-model="form.text" rows="8" :class="{ invalid: errors.text }"
                      placeholder="Write a LEAN algorithm that..."
                      style="font-family:monospace;"></textarea>
            <div class="helper">
              <span :class="{ error: errors.text }">{{ errors.text || `${charCount} / 2000` }}</span>
            </div>
          </div>
        </div>

        <!-- 2: Categorization -->
        <h4 class="section-title">Categorization</h4>
        <div class="form-grid">
          <div class="form-row">
            <label>Strategy type *</label>
            <select v-model="form.strategy_type">
              <option v-for="s in STRATEGY_TYPES" :key="s.value" :value="s.value">{{ s.value }}</option>
            </select>
            <div class="helper">{{ STRATEGY_TYPES.find(s => s.value === form.strategy_type)?.desc }}</div>
          </div>
          <div class="form-row">
            <label>Strategy complexity *<span class="hint"> (strategy logic difficulty)</span></label>
            <div style="display:flex;gap:8px;">
              <label v-for="v in [1,2,3]" :key="v" class="chip-radio" :class="{ active: form.strategy_complexity === v }">
                <input type="radio" v-model.number="form.strategy_complexity" :value="v" style="display:none;" />
                {{ COMPLEXITY_LABELS[v] }}
              </label>
            </div>
          </div>
          <div class="form-row">
            <label>API complexity *<span class="hint"> (LEAN API surface required)</span></label>
            <div style="display:flex;gap:8px;">
              <label v-for="v in [1,2,3]" :key="v" class="chip-radio" :class="{ active: form.api_complexity === v }">
                <input type="radio" v-model.number="form.api_complexity" :value="v" style="display:none;" />
                {{ API_LABELS[v] }}
              </label>
            </div>
          </div>
        </div>

        <!-- 3: LEAN configuration -->
        <h4 class="section-title">LEAN configuration</h4>
        <div class="form-grid">
          <div class="form-row">
            <label>Securities type *</label>
            <select v-model="form.securities_type">
              <option v-for="s in SECURITIES_TYPES" :key="s" :value="s">{{ s }}</option>
            </select>
            <button class="link-btn" style="margin-top:4px;font-size:12px;"
                    @click.prevent="showDetailedSec = !showDetailedSec">
              {{ showDetailedSec ? '▲ hide' : '▼ detailed type' }}
            </button>
            <select v-if="showDetailedSec" v-model="form.securities_type_detailed" style="margin-top:4px;font-size:13px;">
              <option value="">— none —</option>
              <option v-for="s in SECURITIES_DETAIL" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
          <div class="form-row">
            <label>Resolution *</label>
            <select v-model="form.resolution">
              <option v-for="r in RESOLUTIONS" :key="r.value" :value="r.value">{{ r.value }}</option>
            </select>
            <div class="helper">{{ RESOLUTIONS.find(r => r.value === form.resolution)?.desc }}</div>
          </div>
          <div class="form-row full">
            <label>Implementation type *</label>
            <select v-model="form.implementation_type">
              <option v-for="i in IMPLEMENTATION_TYPES" :key="i.value" :value="i.value">{{ i.value }}</option>
            </select>
            <div class="helper">{{ IMPLEMENTATION_TYPES.find(i => i.value === form.implementation_type)?.desc }}</div>
          </div>
          <div class="form-row full">
            <label>Indicators used <span class="hint">(optional; press Enter after each)</span></label>
            <div class="chip-input">
              <span v-for="(ind, i) in form.indicators" :key="ind" class="chip">
                {{ ind }} <button @click="removeIndicator(i)">×</button>
              </span>
              <input type="text" v-model="indicatorDraft" list="indicator-suggestions"
                     @keydown.enter.prevent="addIndicator" @blur="addIndicator"
                     placeholder="RSI" />
              <datalist id="indicator-suggestions">
                <option v-for="ind in INDICATOR_SUGGESTIONS" :key="ind" :value="ind" />
              </datalist>
            </div>
            <div class="helper">Technical indicators referenced in the prompt. Leave empty if none.</div>
          </div>
        </div>

        <!-- 4: Universe and time -->
        <h4 class="section-title">Universe and time</h4>
        <div class="form-grid">
          <div class="form-row full">
            <label>Universe type *</label>
            <select v-model="form.universe_type">
              <option v-for="u in UNIVERSE_TYPES" :key="u.value" :value="u.value">{{ u.value }}</option>
            </select>
            <div class="helper">{{ UNIVERSE_TYPES.find(u => u.value === form.universe_type)?.desc }}</div>
          </div>
          <div v-if="tickerVisible" class="form-row full">
            <label>Tickers * (type, press Enter)</label>
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
          <div v-if="indexVisible" class="form-row">
            <label>Index *</label>
            <select v-model="form.universe_index" :class="{ invalid: errors.universe_index }">
              <option value="">— select —</option>
              <option v-for="ix in INDEX_OPTIONS" :key="ix" :value="ix">{{ ix }}</option>
            </select>
            <div v-if="errors.universe_index" class="helper error">{{ errors.universe_index }}</div>
          </div>
          <div v-if="indexVisible && form.universe_index === 'other'" class="form-row">
            <label>Index (specify) *</label>
            <input type="text" v-model="form.universe_index_other"
                   :class="{ invalid: errors.universe_index_other }"
                   placeholder="e.g. FTSE100" />
            <div v-if="errors.universe_index_other" class="helper error">{{ errors.universe_index_other }}</div>
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

        <!-- 5: Evaluation -->
        <h4 class="section-title">Evaluation</h4>
        <div class="form-grid">
          <div class="form-row">
            <label>Evaluation mode *</label>
            <select v-model="form.evaluation_mode">
              <option v-for="m in EVAL_MODES" :key="m.value" :value="m.value">{{ m.value }}</option>
            </select>
            <div class="helper">{{ EVAL_MODES.find(m => m.value === form.evaluation_mode)?.desc }}</div>
          </div>
          <div class="form-row">
            <label>Interpretation strictness *</label>
            <select v-model.number="form.interpretation_strictness">
              <option v-for="(label, val) in STRICTNESS_LABELS" :key="val" :value="parseInt(val)">{{ label }}</option>
            </select>
          </div>
          <div v-if="form.interpretation_strictness > 0" class="form-row full">
            <label>Underspecification notes</label>
            <input type="text" v-model="form.underspecification_notes"
                   placeholder="e.g. 'goes LONG' doesn't specify exit condition" />
          </div>
          <div class="form-row full posthoc-block">
            <label>Failure mode(s) <span class="hint">— filled in after model evaluation</span></label>
            <div style="display:flex;gap:14px;flex-wrap:wrap;">
              <label v-for="f in FAILURE_MODE_OPTIONS" :key="f.value" style="font-weight:normal;" :title="f.desc">
                <input type="checkbox"
                       :checked="form.failure_mode.includes(f.value)"
                       @change="toggleFailureMode(f.value)" />
                {{ f.value }}
              </label>
            </div>
            <input type="text" v-model="form.failure_notes" class="failure-notes-input"
                   placeholder="Failure notes (optional, for edge cases not captured above)" />
          </div>
        </div>

        <!-- 6: Provenance -->
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
            <div v-if="errors.source_url" class="helper error">{{ errors.source_url }}</div>
          </div>
          <div class="form-row">
            <label>Source date <span class="hint">(when idea was first published)</span></label>
            <input type="date" v-model="form.source_date" />
            <div class="helper">Leave blank for synthetic/original prompts</div>
          </div>
        </div>

        <!-- 7: Documentation -->
        <h4 class="section-title">Documentation</h4>
        <div class="form-grid">
          <div class="form-row full">
            <label>Curator notes *</label>
            <textarea v-model="form.curator_notes" rows="4" :class="{ invalid: errors.curator_notes }"
                      placeholder="What does this prompt test? Why include it?&#10;Edge cases, LEAN-specific gotchas, known ambiguities?&#10;&#10;Example: 'Tests SetWarmUp(200) before SMA(200). Common failure: models trade on day 1 before indicator is ready. No specified exit — judge accepts hold-forever.'"></textarea>
            <div class="helper">
              <span :class="{ error: errors.curator_notes }">{{ errors.curator_notes || `${notesCount} / 80 min` }}</span>
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
  margin: 18px 0 8px; font-size: 13px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.5px;
  color: var(--text-muted, #888);
  border-bottom: 1px solid var(--border, #e5e5e5); padding-bottom: 4px;
}
.helper       { font-size: 12px; color: var(--text-muted, #888); margin-top: 4px; }
.helper.error { color: #d33; }
.hint         { font-weight: normal; font-size: 12px; color: var(--text-muted, #888); }
.link-btn     { background:none; border:none; cursor:pointer; color:var(--text-muted,#888); padding:0; text-decoration:underline; font-size:12px; }
.chip-radio   { padding: 4px 10px; border: 1px solid var(--border, #ccc); border-radius: 4px; cursor: pointer; font-size: 13px; user-select: none; }
.chip-radio.active { background: var(--accent, #1a1a1a); color: #fff; border-color: var(--accent, #1a1a1a); }
.posthoc-block {
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px dashed var(--border, #ccc);
  border-radius: 4px;
  background: rgba(0,0,0,0.02);
}
.failure-notes-input { margin-top: 8px; width: 100%; }
.ai-autofill-bar {
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 16px; padding: 10px 12px;
  background: rgba(99, 102, 241, 0.06);
  border: 1px solid rgba(99, 102, 241, 0.25);
  border-radius: 6px;
}
.ai-autofill-btn {
  padding: 6px 14px; font-size: 13px; font-weight: 500;
  background: #4f46e5; color: #fff; border: none; border-radius: 4px;
  cursor: pointer;
}
.ai-autofill-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ai-autofill-btn:hover:not(:disabled) { background: #4338ca; }
.ai-hint { font-size: 12px; color: var(--text-muted, #666); }
.ai-error-box { margin-bottom: 12px; }
</style>
