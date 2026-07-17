import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'

export function CustomToolsPage() {
  const [tools, setTools] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreateMenu, setShowCreateMenu] = useState(false)
  const [showFormDialog, setShowFormDialog] = useState(false)
  const [showAIDialog, setShowAIDialog] = useState(false)
  const [editingTool, setEditingTool] = useState(null)
  const [testingTool, setTestingTool] = useState(null)
  const [toast, setToast] = useState(null)

  const showToast = (type, msg) => {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 3000)
  }

  const loadTools = () => {
    setLoading(true)
    api.listTools()
      .then(setTools)
      .catch(e => showToast('error', '加载失败: ' + e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadTools()
  }, [])

  const handleDelete = async (e, name) => {
    e.stopPropagation()
    if (!confirm(`确定删除工具 "${name}"?`)) return
    try {
      await api.deleteTool(name)
      setTools(prev => prev.filter(t => t.name !== name))
      showToast('success', '已删除')
    } catch (e) {
      showToast('error', '删除失败: ' + e.message)
    }
  }

  const handleEdit = (e, tool) => {
    e.stopPropagation()
    setEditingTool(tool)
    setShowFormDialog(true)
  }

  const handleTest = (e, tool) => {
    e.stopPropagation()
    setTestingTool(tool)
  }

  if (loading) return <div className="page-workflows"><p>加载中...</p></div>

  return (
    <div className="page-workflows">
      <h1 className="page-title">🛠️ 自定义工具</h1>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {tools.length === 0 && (
          <div className="card" style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
            暂无自定义工具，点击下方按钮创建
          </div>
        )}
        {tools.map(tool => (
          <div
            key={tool.name}
            className="card animate-in"
            style={{ padding: 20 }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: '1rem' }}>{tool.name}</span>
                  <span style={{
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: '0.7rem',
                    background: 'rgba(99,102,241,0.12)',
                    color: 'var(--text-secondary)',
                  }}>{tool.executor_type || tool.executorType || '—'}</span>
                </div>
                {tool.description && (
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: 6 }}>
                    {tool.description}
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-success" onClick={(e) => handleTest(e, tool)}>测试</button>
                <button className="btn btn-primary" onClick={(e) => handleEdit(e, tool)}>编辑</button>
                <button className="btn btn-danger" onClick={(e) => handleDelete(e, tool.name)}>删除</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ position: 'relative', marginTop: 20 }}>
        <button
          className="btn btn-primary"
          onClick={() => setShowCreateMenu(!showCreateMenu)}
        >
          + 创建工具
        </button>
        {showCreateMenu && (
          <div style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            marginTop: 4,
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-primary)',
            borderRadius: 8,
            boxShadow: 'var(--shadow-lg)',
            zIndex: 100,
            minWidth: 200,
            overflow: 'hidden',
          }}>
            <div
              style={{ padding: '10px 16px', cursor: 'pointer', fontSize: '0.85rem' }}
              onClick={() => {
                setShowCreateMenu(false)
                setEditingTool(null)
                setShowFormDialog(true)
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-tertiary)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              📝 表单创建
            </div>
            <div
              style={{ padding: '10px 16px', cursor: 'pointer', fontSize: '0.85rem', borderTop: '1px solid var(--border-primary)' }}
              onClick={() => {
                setShowCreateMenu(false)
                setShowAIDialog(true)
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-tertiary)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              🤖 AI 生成
            </div>
          </div>
        )}
      </div>

      {showFormDialog && (
        <FormCreateDialog
          tool={editingTool}
          onCancel={() => { setShowFormDialog(false); setEditingTool(null) }}
          onSaved={() => {
            setShowFormDialog(false)
            setEditingTool(null)
            loadTools()
          }}
          showToast={showToast}
        />
      )}

      {showAIDialog && (
        <AICreateDialog
          onCancel={() => setShowAIDialog(false)}
          onSaved={() => {
            setShowAIDialog(false)
            loadTools()
          }}
          showToast={showToast}
        />
      )}

      {testingTool && (
        <TestPanel
          tool={testingTool}
          onCancel={() => setTestingTool(null)}
          showToast={showToast}
        />
      )}

      {toast && (
        <div style={{
          position: 'fixed', bottom: 24, right: 24,
          padding: '12px 20px', borderRadius: 8,
          background: toast.type === 'error' ? '#f44336' : '#4caf50',
          color: '#fff', fontSize: '0.85rem', boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          zIndex: 9999, animation: 'fadeIn 0.2s',
        }}>
          {toast.msg}
        </div>
      )}
    </div>
  )
}

const DEFAULT_SKILL_MD = `---
name: my_tool
description: Use this tool when an agent needs to run my custom capability.
executor:
  type: python
  working_dir: "."
  sandbox: process
  timeout_seconds: 60
parameters:
  type: object
  properties:
    query:
      type: string
      description: User input
  required:
    - query
---

# my_tool

Use this skill when the task matches the description above.

## Inputs

- \`query\`: user input string.

## Output

The executor returns a JSON object.
`

const DEFAULT_RUN_PY = `def run(params: dict) -> dict:
    query = params.get("query", "")
    return {"result": query}
`

// ── SKILL.md + run.py 创建/编辑对话框 ──
function FormCreateDialog({ tool, onCancel, onSaved, showToast }) {
  const isEdit = !!tool
  const [skillMd, setSkillMd] = useState(tool?.skill_md || DEFAULT_SKILL_MD)
  const [runPy, setRunPy] = useState(tool?.code || DEFAULT_RUN_PY)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!skillMd.trim()) {
      showToast('error', '请填写 SKILL.md')
      return
    }
    if (!runPy.trim()) {
      showToast('error', '请填写 run.py')
      return
    }
    if (!skillMd.trimStart().startsWith('---')) {
      showToast('error', 'SKILL.md 必须包含 YAML frontmatter')
      return
    }
    if (!runPy.includes('def run')) {
      showToast('error', 'run.py 必须定义 run(params: dict) -> dict')
      return
    }

    setSaving(true)
    try {
      const data = {
        skill_md: skillMd,
        code: runPy,
      }
      if (isEdit) {
        await api.updateTool(tool.name, data)
      } else {
        await api.createTool(data)
      }
      showToast('success', '保存成功')
      onSaved()
    } catch (e) {
      showToast('error', '保存失败: ' + e.message)
    }
    setSaving(false)
  }

  return (
    <div className="prompt-editor-overlay">
      <div
        style={{
          width: '90vw',
          maxWidth: 800,
          maxHeight: '85vh',
          background: 'var(--bg-secondary)',
          border: '1px solid var(--border-secondary)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-lg)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{
          padding: 'var(--space-md) var(--space-lg)',
          borderBottom: '1px solid var(--border-primary)',
        }}>
          <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>
            {isEdit ? '编辑工具' : '创建工具'}
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: 4 }}>
            直接编辑 Agent Skill 文档和 Python 执行器。工具名称、描述、参数和执行设置都来自 SKILL.md。
          </div>
        </div>

        <div style={{ padding: 'var(--space-lg)', overflow: 'auto', flex: 1, display: 'grid', gap: 16 }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">SKILL.md</label>
            <textarea
              style={{
                width: '100%',
                minHeight: 360,
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-primary)',
                borderRadius: 8,
                padding: 12,
                fontFamily: 'monospace',
                fontSize: '0.8rem',
                color: 'var(--text-primary)',
                resize: 'vertical',
                whiteSpace: 'pre',
                overflow: 'auto',
                lineHeight: 1.5,
              }}
              value={skillMd}
              onChange={e => setSkillMd(e.target.value)}
              spellCheck={false}
            />
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">run.py</label>
            <textarea
              style={{
                width: '100%',
                minHeight: 260,
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-primary)',
                borderRadius: 8,
                padding: 12,
                fontFamily: 'monospace',
                fontSize: '0.8rem',
                color: 'var(--text-primary)',
                resize: 'vertical',
                whiteSpace: 'pre',
                overflow: 'auto',
                lineHeight: 1.5,
              }}
              value={runPy}
              onChange={e => setRunPy(e.target.value)}
              spellCheck={false}
            />
          </div>
        </div>

        <div style={{
          padding: 'var(--space-md) var(--space-lg)',
          borderTop: '1px solid var(--border-primary)',
          display: 'flex',
          justifyContent: 'flex-end',
          gap: 'var(--space-sm)',
        }}>
          <button className="btn btn-ghost" onClick={onCancel}>取消</button>
          <button
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── AI 生成对话框 ──
function AICreateDialog({ onCancel, onSaved, showToast }) {
  const [models, setModels] = useState([])
  const [modelName, setModelName] = useState('')
  const [description, setDescription] = useState('')
  const [generatedYaml, setGeneratedYaml] = useState('')
  const [generatedRunPy, setGeneratedRunPy] = useState('')
  const [loadingModels, setLoadingModels] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    Promise.all([
      api.listModels('text'),
      api.listModels('coding'),
    ])
      .then(([textModels, codingModels]) => {
        const map = new Map()
        ;[...textModels, ...codingModels].forEach(m => {
          if (m?.name) map.set(m.name, m)
        })
        const list = Array.from(map.values())
        setModels(list)
        if (list[0]?.name) setModelName(list[0].name)
      })
      .catch(e => showToast('error', '加载模型失败: ' + e.message))
      .finally(() => setLoadingModels(false))
  }, [])

  const handleGenerate = async () => {
    if (!modelName) {
      showToast('error', '请选择模型')
      return
    }
    if (!description.trim()) {
      showToast('error', '请输入需求描述')
      return
    }
    setGenerating(true)
    setGeneratedYaml('')
    setGeneratedRunPy('')
    try {
      const result = await api.createToolAI({
        description: description.trim(),
        preview: true,
        model_name: modelName,
      })
      setGeneratedYaml(result.skill_md || JSON.stringify(result, null, 2))
      setGeneratedRunPy(result.run_py || '')
    } catch (e) {
      showToast('error', '生成失败: ' + e.message)
    }
    setGenerating(false)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.createToolAI({
        description: description.trim(),
        skill_md: generatedYaml,
        run_py: generatedRunPy,
      })
      showToast('success', '保存成功')
      onSaved()
    } catch (e) {
      showToast('error', '保存失败: ' + e.message)
    }
    setSaving(false)
  }

  return (
    <div className="prompt-editor-overlay">
      <div
        style={{
          width: '90vw',
          maxWidth: 800,
          maxHeight: '85vh',
          background: 'var(--bg-secondary)',
          border: '1px solid var(--border-secondary)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-lg)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{
          padding: 'var(--space-md) var(--space-lg)',
          borderBottom: '1px solid var(--border-primary)',
          fontWeight: 600,
          fontSize: '0.95rem',
        }}>
          🤖 AI 生成工具
        </div>

        <div style={{ padding: 'var(--space-lg)', overflow: 'auto', flex: 1 }}>
          <div className="form-group">
            <label className="form-label">模型</label>
            <select
              className="form-input"
              value={modelName}
              onChange={e => setModelName(e.target.value)}
              disabled={loadingModels || generating}
            >
              {models.length === 0 && <option value="">暂无 text/coding 模型</option>}
              {models.map(m => (
                <option key={m.name} value={m.name}>
                  {m.name} ({(m.capabilities || []).join(', ') || '未标注'})
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label">需求描述</label>
            <textarea
              className="form-input"
              style={{ minHeight: 80, resize: 'vertical' }}
              placeholder="例如：创建一个把文本翻译成英文的工具"
              value={description}
              onChange={e => setDescription(e.target.value)}
              disabled={loadingModels || generating || !modelName}
            />
          </div>

          <div style={{ marginBottom: 12 }}>
            <button
              className="btn btn-primary"
              onClick={handleGenerate}
              disabled={loadingModels || generating || !modelName}
            >
              {generating ? '⏳ 生成中...' : '✨ 生成'}
            </button>
          </div>

          {generatedYaml && (
            <div className="form-group">
              <label className="form-label">SKILL.md 预览</label>
              <textarea
                readOnly
                style={{
                  width: '100%',
                  minHeight: 300,
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-primary)',
                  borderRadius: 8,
                  padding: 12,
                  fontFamily: 'monospace',
                  fontSize: '0.8rem',
                  color: 'var(--text-primary)',
                  resize: 'vertical',
                  whiteSpace: 'pre',
                  overflow: 'auto',
                }}
                value={generatedYaml}
              />
            </div>
          )}

          {generatedRunPy && (
            <div className="form-group">
              <label className="form-label">run.py 预览</label>
              <textarea
                readOnly
                style={{
                  width: '100%',
                  minHeight: 220,
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-primary)',
                  borderRadius: 8,
                  padding: 12,
                  fontFamily: 'monospace',
                  fontSize: '0.8rem',
                  color: 'var(--text-primary)',
                  resize: 'vertical',
                  whiteSpace: 'pre',
                  overflow: 'auto',
                }}
                value={generatedRunPy}
              />
            </div>
          )}
        </div>

        <div style={{
          padding: 'var(--space-md) var(--space-lg)',
          borderTop: '1px solid var(--border-primary)',
          display: 'flex',
          justifyContent: 'flex-end',
          gap: 'var(--space-sm)',
        }}>
          <button className="btn btn-ghost" onClick={onCancel}>取消</button>
          <button
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving || !generatedYaml}
          >
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── 测试面板 ──
function getToolSchemaProps(tool) {
  try {
    const params = typeof tool.parameters === 'string'
      ? JSON.parse(tool.parameters)
      : tool.parameters
    return params?.properties || {}
  } catch {
    return {}
  }
}

function buildDefaultParamValues(tool) {
  const props = getToolSchemaProps(tool)
  return Object.fromEntries(
    Object.entries(props)
      .filter(([, schema]) => Object.prototype.hasOwnProperty.call(schema, 'default'))
      .map(([key, schema]) => [key, schema.default])
  )
}

function TestPanel({ tool, onCancel, showToast }) {
  const [paramValues, setParamValues] = useState(() => buildDefaultParamValues(tool))
  const [executing, setExecuting] = useState(false)
  const [result, setResult] = useState(null)
  const [resultError, setResultError] = useState(null)

  // 从 parameters JSON Schema 提取字段
  useEffect(() => {
    setParamValues(buildDefaultParamValues(tool))
  }, [tool])

  const schemaProps = useMemo(() => getToolSchemaProps(tool), [tool])

  const handleExecute = async () => {
    setExecuting(true)
    setResult(null)
    setResultError(null)
    try {
      const res = await api.executeTool(tool.name, paramValues)
      setResult(res)
    } catch (e) {
      setResultError(e.message)
      showToast('error', '执行失败: ' + e.message)
    }
    setExecuting(false)
  }

  const renderParamInput = (key, propSchema) => {
    const type = propSchema.type || 'string'
    const value = paramValues[key] ?? ''

    if (type === 'boolean') {
      return (
        <input
          type="checkbox"
          className="form-input"
          style={{ width: 'auto' }}
          checked={!!value}
          onChange={e => setParamValues(prev => ({ ...prev, [key]: e.target.checked }))}
        />
      )
    }

    if (type === 'number' || type === 'integer') {
      return (
        <input
          type="number"
          className="form-input"
          value={value}
          onChange={e => setParamValues(prev => ({ ...prev, [key]: e.target.value === '' ? '' : Number(e.target.value) }))}
        />
      )
    }

    // string 和其他类型
    return (
      <input
        className="form-input"
        value={value}
        onChange={e => setParamValues(prev => ({ ...prev, [key]: e.target.value }))}
        placeholder={propSchema.description || ''}
      />
    )
  }

  return (
    <div className="prompt-editor-overlay">
      <div
        style={{
          width: '90vw',
          maxWidth: 800,
          maxHeight: '85vh',
          background: 'var(--bg-secondary)',
          border: '1px solid var(--border-secondary)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-lg)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{
          padding: 'var(--space-md) var(--space-lg)',
          borderBottom: '1px solid var(--border-primary)',
          fontWeight: 600,
          fontSize: '0.95rem',
        }}>
          🧪 测试工具 — {tool.name}
        </div>

        <div style={{ padding: 'var(--space-lg)', overflow: 'auto', flex: 1 }}>
          {Object.keys(schemaProps).length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginBottom: 12 }}>
              此工具没有定义参数
            </div>
          ) : (
            <>
              {tool.description && (
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: 16 }}>
                  {tool.description}
                </div>
              )}
              {Object.entries(schemaProps).map(([key, propSchema]) => (
                <div className="form-group" key={key}>
                  <label className="form-label">
                    {key}
                    {propSchema.type && (
                      <span style={{ marginLeft: 6, fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                        ({propSchema.type})
                      </span>
                    )}
                  </label>
                  {renderParamInput(key, propSchema)}
                  {propSchema.description && (
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 4 }}>
                      {propSchema.description}
                    </div>
                  )}
                </div>
              ))}
            </>
          )}

          <div style={{ marginBottom: 16 }}>
            <button
              className="btn btn-primary"
              onClick={handleExecute}
              disabled={executing}
            >
              {executing ? '⏳ 执行中...' : '▶ 执行'}
            </button>
          </div>

          {resultError && (
            <div style={{
              padding: 12,
              background: 'rgba(244,67,54,0.1)',
              border: '1px solid rgba(244,67,54,0.3)',
              borderRadius: 8,
              fontSize: '0.8rem',
              color: '#f44336',
              fontFamily: 'monospace',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            }}>
              {resultError}
            </div>
          )}

          {result !== null && (
            <div>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>
                执行结果
              </div>
              <pre style={{
                background: 'var(--bg-tertiary)',
                padding: 12,
                borderRadius: 8,
                fontSize: '0.75rem',
                overflow: 'auto',
                maxHeight: 300,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}>
                {typeof result === 'string' ? result : JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}
        </div>

        <div style={{
          padding: 'var(--space-md) var(--space-lg)',
          borderTop: '1px solid var(--border-primary)',
          display: 'flex',
          justifyContent: 'flex-end',
          gap: 'var(--space-sm)',
        }}>
          <button className="btn btn-ghost" onClick={onCancel}>关闭</button>
        </div>
      </div>
    </div>
  )
}
