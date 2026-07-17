import { useEffect, useState } from 'react'
import { api } from '../api'

const NODE_MODE_OPTIONS = [
  { value: 'auto', label: '自动判断', hint: '让 LLM 根据需求选择最合适的节点形态' },
  { value: 'processor', label: '普通处理节点', hint: '参考 download / tts / align / compose' },
  { value: 'model', label: '模型调用节点', hint: '参考 recognize，仅暴露运行时 model' },
  { value: 'agent', label: 'Agent 编排节点', hint: '参考 collect / director，可选择自定义工具' },
  { value: 'trigger', label: 'Trigger 入口节点', hint: '参考 cron_trigger，实现 listen' },
  { value: 'listener', label: 'Listener 监听节点', hint: '参考 wechat_channel，实现监听和回复' },
]

function normalizeModelList(value) {
  if (Array.isArray(value)) return value
  if (Array.isArray(value?.models)) return value.models
  return []
}

function mergeModels(...groups) {
  const map = new Map()
  groups.flatMap(normalizeModelList).forEach(model => {
    if (model?.name) map.set(model.name, model)
  })
  return Array.from(map.values())
}

async function loadGenerationModels() {
  const [textResult, codingResult] = await Promise.allSettled([
    api.listModels('text'),
    api.listModels('coding'),
  ])
  let models = mergeModels(
    textResult.status === 'fulfilled' ? textResult.value : [],
    codingResult.status === 'fulfilled' ? codingResult.value : [],
  )

  if (models.length === 0) {
    const allModels = normalizeModelList(await api.listModels())
    models = allModels.filter(model => {
      const caps = Array.isArray(model.capabilities) ? model.capabilities : []
      return caps.length === 0 || caps.includes('text') || caps.includes('coding')
    })
  }

  return models
}

export function CustomNodesPage() {
  const [nodes, setNodes] = useState([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(null)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [editingNodeName, setEditingNodeName] = useState(null)
  const [toast, setToast] = useState(null)

  const showToast = (type, msg) => {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 3000)
  }

  const loadNodes = () => {
    setLoading(true)
    api.listCustomNodes()
      .then(setNodes)
      .catch(e => showToast('error', '加载失败: ' + e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadNodes()
  }, [])

  const handleDelete = async (e, name) => {
    e.stopPropagation()
    if (!confirm(`确定删除节点 "${name}"?`)) return
    try {
      await api.deleteCustomNode(name)
      setNodes(prev => prev.filter(n => n.name !== name))
      showToast('success', '已删除')
    } catch (err) {
      showToast('error', '删除失败: ' + err.message)
    }
  }

  const handleToggle = async (e, name) => {
    e.stopPropagation()
    try {
      const result = await api.toggleCustomNode(name)
      setNodes(prev => prev.map(n => n.name === name ? { ...n, enabled: result.enabled } : n))
      showToast('success', result.enabled ? '已启用' : '已禁用')
    } catch (err) {
      showToast('error', '操作失败: ' + err.message)
    }
  }

  if (loading) return <div className="page-workflows"><p>加载中...</p></div>

  return (
    <div className="page-workflows">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, marginBottom: 20 }}>
        <div>
          <h1 className="page-title" style={{ marginBottom: 6 }}>自定义节点</h1>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            管理本地扩展节点，或用 AI 按参考模板生成节点代码。
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreateDialog(true)}>
          + 创建节点
        </button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {nodes.length === 0 && (
          <div className="card" style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
            暂无自定义节点，点击“创建节点”开始。
          </div>
        )}
        {nodes.map(node => (
          <div
            key={node.name}
            className="card animate-in"
            style={{ padding: 20, cursor: 'pointer' }}
            onClick={() => setExpanded(expanded === node.name ? null : node.name)}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 600, fontSize: '1rem' }}>{node.name}</span>
                  <span style={badgeStyle('rgba(99,102,241,0.12)', 'var(--text-secondary)')}>
                    {node.type || 'custom'}
                  </span>
                  <span style={badgeStyle(node.enabled ? 'rgba(76,175,80,0.15)' : 'rgba(244,67,54,0.15)', node.enabled ? '#4caf50' : '#f44336')}>
                    {node.enabled ? '启用' : '禁用'}
                  </span>
                </div>
                {node.description && (
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.5 }}>
                    {node.description}
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8, flexShrink: 0 }} onClick={e => e.stopPropagation()}>
                <button className="btn btn-success" onClick={(e) => handleToggle(e, node.name)}>
                  {node.enabled ? '禁用' : '启用'}
                </button>
                <button className="btn" onClick={() => setEditingNodeName(node.name)}>
                  编辑
                </button>
                <button className="btn btn-danger" onClick={(e) => handleDelete(e, node.name)}>
                  删除
                </button>
              </div>
            </div>

            {expanded === node.name && (
              <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border-primary)', display: 'grid', gap: 12 }}>
                <PreviewBlock title="Config Schema" value={node.config_schema} />
                <PreviewBlock title="Inputs" value={node.inputs} />
                <PreviewBlock title="Outputs" value={node.outputs} />
              </div>
            )}
          </div>
        ))}
      </div>

      {showCreateDialog && (
        <CreateNodeDialog
          onCancel={() => setShowCreateDialog(false)}
          onSaved={() => {
            setShowCreateDialog(false)
            loadNodes()
          }}
          showToast={showToast}
        />
      )}

      {editingNodeName && (
        <EditNodeDialog
          name={editingNodeName}
          onCancel={() => setEditingNodeName(null)}
          onSaved={() => {
            setEditingNodeName(null)
            loadNodes()
          }}
          showToast={showToast}
        />
      )}

      {toast && <Toast toast={toast} />}
    </div>
  )
}

function PreviewBlock({ title, value }) {
  if (!value) return null
  return (
    <div>
      <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>
        {title}
      </div>
      <pre style={codeBlockStyle}>
        {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}

function EditNodeDialog({ name, onCancel, onSaved, showToast }) {
  const [description, setDescription] = useState('')
  const [code, setCode] = useState('')
  const [models, setModels] = useState([])
  const [modelName, setModelName] = useState('')
  const [aiInstruction, setAiInstruction] = useState('')
  const [aiEditing, setAiEditing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api.getCustomNode(name),
      loadGenerationModels(),
    ])
      .then(([data, modelList]) => {
        setDescription(data.description || '')
        setCode(data.code || '')
        setModels(modelList)
        if (modelList[0]?.name) setModelName(modelList[0].name)
      })
      .catch(e => showToast('error', '加载节点失败: ' + e.message))
      .finally(() => setLoading(false))
  }, [name])

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.updateCustomNode(name, { description, code })
      showToast('success', '节点已保存')
      onSaved()
    } catch (err) {
      showToast('error', '保存失败: ' + err.message)
    }
    setSaving(false)
  }

  const handleAIEdit = async () => {
    if (!modelName) {
      showToast('error', '请选择 AI 编辑模型')
      return
    }
    if (!aiInstruction.trim()) {
      showToast('error', '请输入 AI 修改要求')
      return
    }
    setAiEditing(true)
    try {
      const result = await api.editCustomNodeAI(name, {
        model_name: modelName,
        instruction: aiInstruction.trim(),
        code,
      })
      setCode(result.code || '')
      showToast('success', `AI Agent 已完成修改${result.agent_attempts ? `（${result.agent_attempts} 轮）` : ''}，确认后保存`)
    } catch (err) {
      showToast('error', 'AI 修改失败: ' + err.message)
    }
    setAiEditing(false)
  }

  return (
    <CodeDialog
      title={`编辑自定义节点：${name}`}
      description={description}
      code={code}
      loading={loading}
      saving={saving}
      models={models}
      modelName={modelName}
      aiInstruction={aiInstruction}
      aiEditing={aiEditing}
      onModelChange={setModelName}
      onAIInstructionChange={setAiInstruction}
      onAIEdit={handleAIEdit}
      onDescriptionChange={setDescription}
      onCodeChange={setCode}
      onCancel={onCancel}
      onSave={handleSave}
    />
  )
}

function CreateNodeDialog({ onCancel, onSaved, showToast }) {
  const [models, setModels] = useState([])
  const [tools, setTools] = useState([])
  const [modelName, setModelName] = useState('')
  const [nodeMode, setNodeMode] = useState('auto')
  const [selectedTools, setSelectedTools] = useState([])
  const [description, setDescription] = useState('')
  const [generatedCode, setGeneratedCode] = useState('')
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    Promise.all([
      loadGenerationModels(),
      api.listTools().catch(() => []),
    ])
      .then(([modelList, toolList]) => {
        setModels(modelList)
        setTools(Array.isArray(toolList) ? toolList : [])
        if (modelList[0]?.name) setModelName(modelList[0].name)
      })
      .catch(e => showToast('error', '加载生成配置失败: ' + e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (nodeMode !== 'agent') setSelectedTools([])
  }, [nodeMode])

  const handleGenerate = async () => {
    if (!modelName) {
      showToast('error', '请选择生成模型')
      return
    }
    if (!description.trim()) {
      showToast('error', '请输入节点需求')
      return
    }
    setGenerating(true)
    setGeneratedCode('')
    try {
      const result = await api.createCustomNode({
        description: description.trim(),
        preview: true,
        model_name: modelName,
        node_mode: nodeMode,
        tool_names: nodeMode === 'agent' ? selectedTools : [],
      })
      setGeneratedCode(result.code || result.generated_code || '')
    } catch (err) {
      showToast('error', '生成失败: ' + err.message)
    }
    setGenerating(false)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.createCustomNode({ description: description.trim(), code: generatedCode })
      showToast('success', '保存成功')
      onSaved()
    } catch (err) {
      showToast('error', '保存失败: ' + err.message)
    }
    setSaving(false)
  }

  const selectedMode = NODE_MODE_OPTIONS.find(item => item.value === nodeMode)

  return (
    <div className="prompt-editor-overlay">
      <div style={dialogStyle} onClick={(e) => e.stopPropagation()}>
        <div style={dialogHeaderStyle}>
          <div style={{ fontWeight: 600, fontSize: '1rem' }}>AI 生成自定义节点</div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', marginTop: 4 }}>
            生成用模型只负责写代码；节点运行时模型在节点属性里从全局模型池选择。
          </div>
        </div>

        <div style={{ padding: 'var(--space-lg)', overflow: 'auto', flex: 1, display: 'grid', gap: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">生成模型</label>
              <select className="form-input" value={modelName} onChange={e => setModelName(e.target.value)} disabled={loading || generating}>
                {models.length === 0 && <option value="">暂无 text/coding 模型</option>}
                {models.map(m => (
                  <option key={m.name} value={m.name}>
                    {m.name} ({(m.capabilities || []).join(', ') || '未标注'})
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">参考节点/节点类型</label>
              <select className="form-input" value={nodeMode} onChange={e => setNodeMode(e.target.value)} disabled={loading || generating}>
                {NODE_MODE_OPTIONS.map(option => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
              {selectedMode && (
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: 6 }}>
                  {selectedMode.hint}
                </div>
              )}
            </div>
          </div>

          {nodeMode === 'agent' && (
            <ToolSelector
              tools={tools}
              selectedTools={selectedTools}
              setSelectedTools={setSelectedTools}
              disabled={generating}
            />
          )}

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">节点需求</label>
            <textarea
              className="form-input"
              style={{ minHeight: 90, resize: 'vertical' }}
              value={description}
              onChange={e => setDescription(e.target.value)}
              disabled={generating}
              placeholder="描述节点要做什么、输入输出是什么、是否需要调用模型或工具"
            />
          </div>

          <button className="btn btn-primary" onClick={handleGenerate} disabled={loading || generating || !modelName}>
            {generating ? '生成中...' : '生成代码'}
          </button>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">生成代码</label>
            <textarea
              className="form-input"
              value={generatedCode}
              onChange={e => setGeneratedCode(e.target.value)}
              spellCheck={false}
              style={codeTextareaStyle}
              placeholder="生成后可在这里预览和微调 node.py"
            />
          </div>
        </div>

        <div style={dialogFooterStyle}>
          <button className="btn btn-ghost" onClick={onCancel} disabled={saving}>取消</button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving || !generatedCode.trim()}>
            {saving ? '保存中...' : '保存节点'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ToolSelector({ tools, selectedTools, setSelectedTools, disabled }) {
  const toggleTool = (name) => {
    setSelectedTools(prev => prev.includes(name) ? prev.filter(item => item !== name) : [...prev, name])
  }

  return (
    <div className="card" style={{ padding: 14, background: 'var(--bg-tertiary)', display: 'grid', gap: 10 }}>
      <div style={{ fontWeight: 600, fontSize: '0.86rem' }}>Agent 可用工具</div>
      {tools.length === 0 ? (
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.5 }}>
          当前没有自定义工具，仍会生成纯 LLM Agent 节点。
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 }}>
          {tools.map(tool => (
            <label key={tool.name} style={toolItemStyle}>
              <input
                type="checkbox"
                checked={selectedTools.includes(tool.name)}
                onChange={() => toggleTool(tool.name)}
                disabled={disabled}
              />
              <span style={{ minWidth: 0 }}>
                <span style={{ display: 'block', fontWeight: 600, fontSize: '0.82rem' }}>{tool.name}</span>
                {tool.description && (
                  <span style={{ display: 'block', color: 'var(--text-secondary)', fontSize: '0.76rem', marginTop: 3 }}>
                    {tool.description}
                  </span>
                )}
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

function CodeDialog({
  title,
  description,
  code,
  loading,
  saving,
  models = [],
  modelName = '',
  aiInstruction = '',
  aiEditing = false,
  onModelChange,
  onAIInstructionChange,
  onAIEdit,
  onDescriptionChange,
  onCodeChange,
  onCancel,
  onSave,
}) {
  return (
    <div className="prompt-editor-overlay">
      <div style={dialogStyle} onClick={(e) => e.stopPropagation()}>
        <div style={dialogHeaderStyle}>{title}</div>
        <div style={{ padding: 'var(--space-lg)', overflow: 'auto', flex: 1, display: 'grid', gap: 14 }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">描述</label>
            <input className="form-input" value={description} onChange={e => onDescriptionChange(e.target.value)} disabled={loading || saving} />
          </div>
          {onAIEdit && (
            <div className="card" style={{ padding: 14, background: 'var(--bg-tertiary)', display: 'grid', gap: 10 }}>
              <div style={{ fontWeight: 600, fontSize: '0.86rem' }}>AI Agent 修改代码</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'minmax(180px, 260px) minmax(0, 1fr) auto', gap: 10, alignItems: 'end' }}>
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label">模型</label>
                  <select
                    className="form-input"
                    value={modelName}
                    onChange={e => onModelChange?.(e.target.value)}
                    disabled={loading || saving || aiEditing}
                  >
                    {models.length === 0 && <option value="">暂无 text/coding 模型</option>}
                    {models.map(model => (
                      <option key={model.name} value={model.name}>
                        {model.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label">修改要求</label>
                  <input
                    className="form-input"
                    value={aiInstruction}
                    onChange={e => onAIInstructionChange?.(e.target.value)}
                    disabled={loading || saving || aiEditing}
                    placeholder="例如：增加停止标记检查、把输出端口改成 result、修复 JSON 解析失败"
                  />
                </div>
                <button
                  className="btn btn-primary"
                  onClick={onAIEdit}
                  disabled={loading || saving || aiEditing || !modelName || !aiInstruction.trim()}
                >
                  {aiEditing ? '修改中...' : 'AI 修改'}
                </button>
              </div>
            </div>
          )}
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">node.py</label>
            <textarea
              className="form-input"
              value={code}
              onChange={e => onCodeChange(e.target.value)}
              disabled={loading || saving}
              spellCheck={false}
              style={codeTextareaStyle}
            />
          </div>
        </div>
        <div style={dialogFooterStyle}>
          <button className="btn btn-ghost" onClick={onCancel} disabled={saving}>取消</button>
          <button className="btn btn-primary" onClick={onSave} disabled={loading || saving || !code.trim()}>
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Toast({ toast }) {
  return (
    <div style={{
      position: 'fixed',
      bottom: 24,
      right: 24,
      padding: '12px 20px',
      borderRadius: 8,
      background: toast.type === 'error' ? '#f44336' : '#4caf50',
      color: '#fff',
      fontSize: '0.85rem',
      boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
      zIndex: 9999,
      animation: 'fadeIn 0.2s',
    }}>
      {toast.msg}
    </div>
  )
}

function badgeStyle(bg, color) {
  return {
    padding: '2px 8px',
    borderRadius: 4,
    background: bg,
    color,
    fontSize: '0.72rem',
    fontWeight: 500,
  }
}

const dialogStyle = {
  width: '92vw',
  maxWidth: 980,
  maxHeight: '88vh',
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border-secondary)',
  borderRadius: 'var(--radius-lg)',
  boxShadow: 'var(--shadow-lg)',
  display: 'flex',
  flexDirection: 'column',
  overflow: 'hidden',
}

const dialogHeaderStyle = {
  padding: 'var(--space-md) var(--space-lg)',
  borderBottom: '1px solid var(--border-primary)',
  fontWeight: 600,
}

const dialogFooterStyle = {
  padding: 'var(--space-md) var(--space-lg)',
  borderTop: '1px solid var(--border-primary)',
  display: 'flex',
  justifyContent: 'flex-end',
  gap: 'var(--space-sm)',
}

const codeTextareaStyle = {
  minHeight: '48vh',
  fontFamily: 'Consolas, Monaco, monospace',
  fontSize: 12,
  lineHeight: 1.5,
  resize: 'vertical',
  whiteSpace: 'pre',
}

const codeBlockStyle = {
  background: 'var(--bg-tertiary)',
  padding: 12,
  borderRadius: 8,
  fontSize: '0.75rem',
  overflow: 'auto',
  maxHeight: 200,
  margin: 0,
}

const toolItemStyle = {
  display: 'flex',
  gap: 8,
  alignItems: 'flex-start',
  padding: 10,
  border: '1px solid var(--border-primary)',
  borderRadius: 8,
  cursor: 'pointer',
}
