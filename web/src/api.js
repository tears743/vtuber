/**
 * API 服务层 — 与后端通信
 * 动态获取当前端口，不再硬编码 8100
 */
const BASE_URL = `${window.location.protocol}//${window.location.host}`

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// ── Workflows ──
export const api = {
  // Workflows
  listWorkflows: () => request('/api/workflows'),
  getWorkflow: (id) => request(`/api/workflows/${id}`),
  createWorkflow: (data) => request('/api/workflows', { method: 'POST', body: JSON.stringify(data) }),
  updateWorkflow: (id, data) => request(`/api/workflows/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteWorkflow: (id) => request(`/api/workflows/${id}`, { method: 'DELETE' }),

  // Nodes
  listNodes: () => request('/api/nodes'),
  listNodeCategories: () => request('/api/nodes/categories'),

  // Settings
  listModels: () => request('/api/settings/models'),
  createModel: (data) => request('/api/settings/models', { method: 'POST', body: JSON.stringify(data) }),
  updateModel: (id, data) => request(`/api/settings/models/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteModel: (id) => request(`/api/settings/models/${id}`, { method: 'DELETE' }),
  testModel: (id) => request(`/api/settings/models/${id}/test`, { method: 'POST' }),

  // Runs
  startRun: (data) => request('/api/run', { method: 'POST', body: JSON.stringify(data) }),
  stopRun: () => request('/api/run/stop', { method: 'POST' }),
  getRunStatus: () => request('/api/run/status'),
  getRunHistory: (workflowId) => request(`/api/runs/history/${workflowId}`),
  getRunDetail: (runId) => request(`/api/runs/${runId}`),
  runNode: (data) => request('/api/run/node', { method: 'POST', body: JSON.stringify(data) }),

  // Cache
  clearCache: (data) => request('/api/cache/clear', { method: 'POST', body: JSON.stringify(data) }),

  // Scripts / Timeline
  listScriptDates: () => request('/api/scripts/dates'),
  getScript: (date, id, aligned = false) => request(`/api/scripts/${date}/${id}?aligned=${aligned}`),
  getScriptCompare: (date, id) => request(`/api/scripts/${date}/${id}/compare`),
}

// ── WebSocket ──
export function createRunSocket(onMessage) {
  const ws = new WebSocket(`${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/run`)
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      onMessage(data)
    } catch (e) {
      console.warn('WS parse error:', e)
    }
  }
  ws.onclose = () => {
    console.log('WS closed, reconnecting in 3s...')
    setTimeout(() => createRunSocket(onMessage), 3000)
  }
  // 心跳
  const heartbeat = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) ws.send('ping')
  }, 30000)
  ws.addEventListener('close', () => clearInterval(heartbeat))
  return ws
}
