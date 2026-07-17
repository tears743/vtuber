/**
 * API 服务层 — 与后端通信
 * 动态获取当前端口，不再硬编码 8100
 */
const isViteDevServer = window.location.port === '5173'
const currentOrigin = `${window.location.protocol}//${window.location.host}`
const DEFAULT_BASE_URL = import.meta.env.VITE_API_BASE_URL ||
  (isViteDevServer ? 'http://127.0.0.1:8100' : currentOrigin)
let resolvedApiBaseUrl = DEFAULT_BASE_URL

function apiBaseCandidates() {
  if (!isViteDevServer) return [resolvedApiBaseUrl]
  const candidates = [
    import.meta.env.VITE_API_BASE_URL,
    resolvedApiBaseUrl,
    'http://127.0.0.1:8100',
    'http://localhost:8100',
    ...Array.from({ length: 9 }, (_, i) => `http://127.0.0.1:${8101 + i}`),
  ].filter(Boolean)
  return Array.from(new Set(candidates))
}

async function fetchWithApiFallback(path, options) {
  let lastError = null
  let lastResponse = null
  for (const baseUrl of apiBaseCandidates()) {
    try {
      const res = await fetch(`${baseUrl}${path}`, options)
      const rawText = await res.text()
      lastResponse = { res, rawText, baseUrl }
      const looksLikeHtml = rawText.trim().startsWith('<!doctype') || rawText.trim().startsWith('<html')
      if (looksLikeHtml && isViteDevServer && path.startsWith('/api/')) {
        lastError = new Error('接口返回了前端页面，不是 JSON。请确认后端已重启，并且前端接口地址指向后端服务。')
        continue
      }
      if (isViteDevServer && path.startsWith('/api/') && [404, 405].includes(res.status)) {
        continue
      }
      resolvedApiBaseUrl = baseUrl
      return { res, rawText }
    } catch (error) {
      lastError = error
    }
  }
  if (lastResponse) {
    resolvedApiBaseUrl = lastResponse.baseUrl
    return { res: lastResponse.res, rawText: lastResponse.rawText }
  }
  throw lastError || new Error('无法连接后端服务')
}

async function request(path, options = {}) {
  const { res, rawText } = await fetchWithApiFallback(path, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  const contentType = res.headers.get('content-type') || ''
  let data = null
  if (rawText) {
    try {
      data = contentType.includes('application/json') ? JSON.parse(rawText) : JSON.parse(rawText)
    } catch {
      const looksLikeHtml = rawText.trim().startsWith('<!doctype') || rawText.trim().startsWith('<html')
      if (looksLikeHtml) {
        throw new Error('接口返回了前端页面，不是 JSON。请确认后端已重启，并且前端接口地址指向后端服务。')
      }
      throw new Error(rawText.slice(0, 200) || '接口返回内容无法解析')
    }
  }
  if (!res.ok) {
    throw new Error(data?.detail || data?.message || res.statusText || `HTTP ${res.status}`)
  }
  return data
}

async function requestArray(path, key, options = {}) {
  const data = await request(path, options)
  return Array.isArray(data) ? data : (data?.[key] || [])
}

// ── Workflows ──
export const api = {
  // Workflows
  listWorkflows: () => request('/api/workflows'),
  getWorkflow: (id) => request(`/api/workflows/${id}`),
  createWorkflow: (data) => request('/api/workflows', { method: 'POST', body: JSON.stringify(data) }),
  updateWorkflow: (id, data) => request(`/api/workflows/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteWorkflow: (id) => request(`/api/workflows/${id}`, { method: 'DELETE' }),

  // Workflow Templates & Actions
  saveAsTemplate: (id, name) => request(`/api/workflows/${id}/template`, { method: 'POST', body: JSON.stringify({template_name: name}) }),
  listTemplates: () => request('/api/workflow-templates'),
  createFromTemplate: (name) => request(`/api/workflow-templates/${name}/create`, { method: 'POST' }),
  duplicateWorkflow: (id) => request(`/api/workflows/${id}/duplicate`, { method: 'POST' }),
  exportWorkflow: (id) => request(`/api/workflows/${id}/export`),
  importWorkflow: (data) => request('/api/workflows/import', { method: 'POST', body: JSON.stringify(data) }),
  deleteTemplate: (name) => request(`/api/workflow-templates/${name}`, { method: 'DELETE' }),
  previewAIWorkflow: (data) => request('/api/workflows/ai/preview', { method: 'POST', body: JSON.stringify(data) }),
  confirmAIWorkflow: (data) => request('/api/workflows/ai/confirm', { method: 'POST', body: JSON.stringify(data) }),

  // Nodes
  listNodes: () => request('/api/nodes'),
  listNodeCategories: () => request('/api/nodes/categories'),

  // Settings
  listModels: (capability) => request(`/api/settings/models${capability ? `?capability=${encodeURIComponent(capability)}` : ''}`),
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

  // Custom Nodes
  listCustomNodes: () => requestArray('/api/custom-nodes', 'nodes'),
  getCustomNode: (name) => request(`/api/custom-nodes/${name}`),
  createCustomNode: (data) => request('/api/custom-nodes/create', { method: 'POST', body: JSON.stringify(data) }),
  updateCustomNode: (name, data) => request(`/api/custom-nodes/${name}`, { method: 'PUT', body: JSON.stringify(data) }),
  editCustomNodeAI: (name, data) => request(`/api/custom-nodes/${name}/ai-edit`, { method: 'POST', body: JSON.stringify(data) }),
  deleteCustomNode: (name) => request(`/api/custom-nodes/${name}`, { method: 'DELETE' }),
  toggleCustomNode: (name) => request(`/api/custom-nodes/${name}/toggle`, { method: 'POST' }),

  // Cache
  clearCache: (data) => request('/api/cache/clear', { method: 'POST', body: JSON.stringify(data) }),
  clearNodeCache: (data) => request('/api/cache/node/clear', { method: 'POST', body: JSON.stringify(data) }),

  // Scripts / Timeline
  listScriptDates: () => request('/api/scripts/dates'),
  getScript: (date, id, aligned = false) => request(`/api/scripts/${date}/${id}?aligned=${aligned}`),
  getScriptCompare: (date, id) => request(`/api/scripts/${date}/${id}/compare`),

  // Custom Tools
  listTools: () => requestArray('/api/tools', 'tools'),
  getTool: (name) => request(`/api/tools/${name}`),
  createTool: (data) => request('/api/tools', { method: 'POST', body: JSON.stringify(data) }),
  updateTool: (name, data) => request(`/api/tools/${name}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteTool: (name) => request(`/api/tools/${name}`, { method: 'DELETE' }),
  executeTool: (name, params) => request(`/api/tools/${name}/execute`, { method: 'POST', body: JSON.stringify({params}) }),
  createToolAI: (data) => request('/api/tools/create', { method: 'POST', body: JSON.stringify(data) }),
}

// ── WebSocket ──
export function createRunSocket(onMessage) {
  const wsBase = import.meta.env.VITE_WS_BASE_URL ||
    resolvedApiBaseUrl.replace(/^http/, 'ws')
  const ws = new WebSocket(`${wsBase}/ws/run`)
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
