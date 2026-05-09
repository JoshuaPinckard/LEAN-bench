<script setup>
import { ref } from 'vue'

const FROZEN_DATE = '2026-05-09'

const OPENAI_KEY     = import.meta.env.VITE_OPENAI_API_KEY
const GEMINI_KEY     = import.meta.env.VITE_GEMINI_API_KEY
const ANTHROPIC_KEY  = import.meta.env.VITE_ANTHROPIC_API_KEY

const models = ref([
  { id: 'claude-opus-4-7',        label: 'claude-opus-4.7',   provider: 'anthropic', selected: false },
  { id: 'claude-opus-4-6',        label: 'claude-opus-4.6',   provider: 'anthropic', selected: false },
  { id: 'claude-sonnet-4-6',      label: 'claude-sonnet-4.6', provider: 'anthropic', selected: false },
  { id: 'gpt-5.5-2026-04-23',     label: 'gpt-5.5',           provider: 'openai',    selected: false },
  { id: 'gpt-5.4-2026-05-09',     label: 'gpt-5.4',           provider: 'openai',    selected: false },
  { id: 'gemini-3.1-pro-preview', label: 'gemini-3.1-pro',    provider: 'gemini',    selected: false },
])

const prompt  = ref('')
const sending = ref(false)

async function sendToOpenAI(modelId, text) {
  const res = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${OPENAI_KEY}` },
    body: JSON.stringify({ model: modelId, messages: [{ role: 'user', content: text }] }),
  })
  return res.json()
}

async function sendToAnthropic(modelId, text) {
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': ANTHROPIC_KEY,
      'anthropic-version': '2023-06-01',
      'anthropic-dangerous-direct-browser-access': 'true',
    },
    body: JSON.stringify({ model: modelId, max_tokens: 1024, messages: [{ role: 'user', content: text }] }),
  })
  return res.json()
}

async function sendToGemini(modelId, text) {
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${modelId}:generateContent?key=${GEMINI_KEY}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contents: [{ parts: [{ text }] }] }),
    }
  )
  return res.json()
}

async function send() {
  const selected = models.value.filter(m => m.selected)
  if (!selected.length || !prompt.value.trim()) return
  sending.value = true
  const text = prompt.value.trim()

  await Promise.all(selected.map(async m => {
    try {
      let result
      if (m.provider === 'openai')    result = await sendToOpenAI(m.id, text)
      if (m.provider === 'anthropic') result = await sendToAnthropic(m.id, text)
      if (m.provider === 'gemini')    result = await sendToGemini(m.id, text)
      console.log(`[${m.label}]`, result)
    } catch (err) {
      console.error(`[${m.label}] error:`, err)
    }
  }))

  sending.value = false
}
</script>

<template>
  <div>
    <p>frozen: {{ FROZEN_DATE }}</p>
    <div v-for="m in models" :key="m.id">
      <label><input type="checkbox" v-model="m.selected" /> {{ m.label }}</label>
    </div>
    <br />
    <textarea v-model="prompt" rows="6" cols="80" placeholder="prompt"></textarea>
    <br />
    <button @click="send" :disabled="sending">{{ sending ? 'sending...' : 'send' }}</button>
  </div>
</template>
