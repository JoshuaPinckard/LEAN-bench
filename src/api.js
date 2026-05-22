// Single source of truth for backend HTTP. Components must NEVER fetch directly.

const BASE = 'http://localhost:8010'

async function req(method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json()).detail || '' } catch {}
    throw new Error(`${method} ${path} → ${res.status} ${res.statusText}${detail ? ': ' + detail : ''}`)
  }
  return res.json()
}

export const api = {
  models:     ()                                 => req('GET',    '/api/models'),
  conditions: ()                                 => req('GET',    '/api/conditions'),
  stats:      ()                                 => req('GET',    '/api/stats'),

  listPrompts:  (params = {})                    => {
    const q = new URLSearchParams()
    if (params.limit  != null) q.set('limit',  params.limit)
    if (params.offset != null) q.set('offset', params.offset)
    if (params.search)         q.set('search', params.search)
    const qs = q.toString()
    return req('GET', `/api/prompts${qs ? '?' + qs : ''}`)
  },
  getPrompt:    (id)                             => req('GET',    `/api/prompts/${id}`),
  createPrompt: (body)                           => req('POST',   '/api/prompts', body),
  updatePrompt: (id, body)                       => req('PATCH',  `/api/prompts/${id}`, body),
  deletePrompt: (id)                             => req('DELETE', `/api/prompts/${id}`),

  generate:     (body)                           => req('POST',   '/api/generate', body),
  getCall:      (id)                             => req('GET',    `/api/calls/${id}`),

  schemaAutofill: (promptText)                   => req('POST',   '/api/schema/autofill', { prompt_text: promptText }),

  distribution: ()                               => req('GET',    '/api/stats/distribution'),
}
