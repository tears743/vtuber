import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

export function CustomWorkflowsPage() {
  const [workflows, setWorkflows] = useState([])
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [toast, setToast] = useState(null)
  const [templateDialogId, setTemplateDialogId] = useState(null)
  const [templateName, setTemplateName] = useState('')
  const [showAIDialog, setShowAIDialog] = useState(false)
  const fileInputRef = useRef(null)
  const navigate = useNavigate()

  const showToast = (type, msg) => {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 3000)
  }

  const loadData = () => {
    setLoading(true)
    Promise.all([
      api.listWorkflows(),
      api.listTemplates(),
    ])
      .then(([wfs, tpls]) => {
        setWorkflows(wfs)
        setTemplates(tpls)
      })
      .catch(e => showToast('error', '加载失败: ' + e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleExport = async (e, id, name) => {
    e.stopPropagation()
    try {
      const data = await api.exportWorkflow(id)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${name || id}.json`
      a.click()
      URL.revokeObjectURL(url)
      showToast('success', '已导出')
    } catch (e) {
      showToast('error', '导出失败: ' + e.message)
    }
  }

  const handleDuplicate = async (e, id) => {
    e.stopPropagation()
    try {
      const result = await api.duplicateWorkflow(id)
      showToast('success', `已复制: ${result.name}`)
      loadData()
    } catch (e) {
      showToast('error', '复制失败: ' + e.message)
    }
  }

  const handleDelete = async (e, id) => {
    e.stopPropagation()
    if (!confirm(`确定删除工作流 "${id}"?`)) return
    try {
      await api.deleteWorkflow(id)
      setWorkflows(prev => prev.filter(w => w.id !== id))
      showToast('success', '已删除')
    } catch (e) {
      showToast('error', '删除失败: ' + e.message)
    }
  }

  const handleSaveAsTemplate = async (id) => {
    const name = templateName.trim()
    if (!name) {
      showToast('error', '请输入模板名称')
      return
    }
    try {
      await api.saveAsTemplate(id, name)
      showToast('success', '模板已保存')
      setTemplateDialogId(null)
      setTemplateName('')
      loadData()
    } catch (e) {
      showToast('error', '保存模板失败: ' + e.message)
    }
  }

  const handleCreateFromTemplate = async (name) => {
    try {
      const result = await api.createFromTemplate(name)
      showToast('success', `已创建: ${result.name}`)
      navigate(`/workflow/${result.id}`)
    } catch (e) {
      showToast('error', '创建失败: ' + e.message)
    }
  }

  const handleDeleteTemplate = async (name) => {
    if (!confirm(`确定删除模板 "${name}"?`)) return
    try {
      await api.deleteTemplate(name)
      setTemplates(prev => prev.filter(t => t.name !== name))
      showToast('success', '模板已删除')
    } catch (e) {
      showToast('error', '删除模板失败: ' + e.message)
    }
  }

  const handleImportFile = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      const result = await api.importWorkflow(data)
      showToast('success', `已导入: ${result.name}`)
      loadData()
    } catch (e) {
      showToast('error', '导入失败: ' + (e.message || '无效的 JSON 文件'))
    }
    e.target.value = ''
  }

  if (loading) return <div className="page-workflows"><p>加载中...</p></div>

  return (
    <div className="page-workflows">
      <h1 className="page-title">📦 自定义工作流</h1>

      {/* 工作流列表 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ fontSize: '1.1rem', fontWeight: 600 }}>工作流列表</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            className="btn btn-primary"
            onClick={() => setShowAIDialog(true)}
          >
            AI 生成工作流
          </button>
          <button
            className="btn btn-primary"
            onClick={() => fileInputRef.current?.click()}
          >
            📥 导入工作流
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          style={{ display: 'none' }}
          onChange={handleImportFile}
        />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 32 }}>
        {workflows.length === 0 && (
          <div className="card" style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
            暂无工作流
          </div>
        )}
        {workflows.map(wf => (
          <div
            key={wf.id}
            className="card animate-in"
            style={{ padding: 20, cursor: 'pointer' }}
            onClick={() => navigate(`/workflow/${wf.id}`)}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: '1rem' }}>{wf.name}</div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 4 }}>
                  📦 {wf.node_count} 节点 · 📅 {wf.updated_at?.slice(0, 10) || '—'}
                  {wf.draft && (
                    <span style={{
                      marginLeft: 8,
                      padding: '2px 6px',
                      borderRadius: 4,
                      background: 'rgba(245,158,11,0.16)',
                      color: '#f59e0b',
                      fontSize: '0.7rem',
                    }}>
                      草稿
                    </span>
                  )}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }} onClick={e => e.stopPropagation()}>
                {templateDialogId === wf.id ? (
                  <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                    <input
                      className="form-input"
                      style={{ width: 140 }}
                      autoFocus
                      placeholder="模板名称"
                      value={templateName}
                      onChange={e => setTemplateName(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') handleSaveAsTemplate(wf.id)
                        if (e.key === 'Escape') { setTemplateDialogId(null); setTemplateName('') }
                      }}
                    />
                    <button className="btn btn-primary" onClick={() => handleSaveAsTemplate(wf.id)}>保存</button>
                    <button className="btn btn-ghost" onClick={() => { setTemplateDialogId(null); setTemplateName('') }}>取消</button>
                  </div>
                ) : (
                  <>
                    <button className="btn" onClick={(e) => { e.stopPropagation(); setTemplateDialogId(wf.id); setTemplateName(wf.name) }}>
                      存为模板
                    </button>
                    <button className="btn" onClick={(e) => handleExport(e, wf.id, wf.name)}>
                      导出
                    </button>
                    <button className="btn" onClick={(e) => handleDuplicate(e, wf.id)}>
                      复制
                    </button>
                    <button className="btn btn-danger" onClick={(e) => handleDelete(e, wf.id)}>
                      删除
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 模板列表 */}
      <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: 16 }}>模板列表</h2>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {templates.length === 0 && (
          <div className="card" style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
            暂无模板，从工作流保存模板后会显示在这里
          </div>
        )}
        {templates.map(tpl => (
          <div
            key={tpl.name}
            className="card animate-in"
            style={{ padding: 20 }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: '1rem' }}>{tpl.name}</span>
                  {tpl.workflow_name && (
                    <span style={{
                      padding: '2px 8px',
                      borderRadius: 4,
                      fontSize: '0.7rem',
                      background: 'rgba(99,102,241,0.12)',
                      color: 'var(--text-secondary)',
                    }}>{tpl.workflow_name}</span>
                  )}
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 4 }}>
                  📦 {tpl.node_count} 节点 · 📅 {tpl.created_at?.slice(0, 10) || '—'}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-primary" onClick={() => handleCreateFromTemplate(tpl.name)}>
                  从模板创建
                </button>
                <button className="btn btn-danger" onClick={() => handleDeleteTemplate(tpl.name)}>
                  删除
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {showAIDialog && (
        <AIWorkflowDialog
          onCancel={() => setShowAIDialog(false)}
          onSaved={(result) => {
            setShowAIDialog(false)
            showToast('success', result.draft ? '已保存为草稿' : '工作流已创建')
            navigate(`/workflow/${result.id}`)
          }}
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

function AIWorkflowDialog({ onCancel, onSaved, showToast }) {
  const [models, setModels] = useState([])
  const [modelName, setModelName] = useState('')
  const [goal, setGoal] = useState('')
  const [preview, setPreview] = useState(null)
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
    if (!goal.trim()) {
      showToast('error', '请输入工作流目标')
      return
    }
    setGenerating(true)
    setPreview(null)
    try {
      const result = await api.previewAIWorkflow({
        model_name: modelName,
        goal: goal.trim(),
      })
      setPreview(result)
    } catch (e) {
      showToast('error', '生成失败: ' + e.message)
    }
    setGenerating(false)
  }

  const handleConfirm = async () => {
    if (!preview?.workflow) return
    setSaving(true)
    try {
      const result = await api.confirmAIWorkflow({
        workflow: preview.workflow,
        goal: goal.trim(),
        plan_text: preview.plan_text || '',
        validation_errors: preview.validation_errors || [],
      })
      onSaved(result)
    } catch (e) {
      showToast('error', '保存失败: ' + e.message)
    }
    setSaving(false)
  }

  const workflow = preview?.workflow || {}
  const validationErrors = preview?.validation_errors || []
  const nodesById = new Map((workflow.nodes || []).map(node => [node.id, node]))
  const portList = (ports = []) => ports.map(port => `${port.name}:${port.type || '*'}`).join(', ') || '无'

  return (
    <div className="prompt-editor-overlay">
      <div
        style={{
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
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{
          padding: 'var(--space-md) var(--space-lg)',
          borderBottom: '1px solid var(--border-primary)',
          fontWeight: 600,
          fontSize: '0.95rem',
        }}>
          AI 生成工作流
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
            <label className="form-label">工作流目标</label>
            <textarea
              className="form-input"
              style={{ minHeight: 90, resize: 'vertical' }}
              placeholder="例如：每天早上采集微博和 GitHub 热点，下载素材，生成 AI 日报视频并发送到微信"
              value={goal}
              onChange={e => setGoal(e.target.value)}
              disabled={generating}
            />
          </div>

          <button
            className="btn btn-primary"
            onClick={handleGenerate}
            disabled={loadingModels || generating || !modelName}
          >
            {generating ? '生成中...' : '生成计划'}
          </button>

          {preview && (
            <div style={{ marginTop: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
              {validationErrors.length > 0 && (
                <div style={{
                  padding: 12,
                  border: '1px solid rgba(245,158,11,0.35)',
                  background: 'rgba(245,158,11,0.1)',
                  borderRadius: 8,
                  color: '#f59e0b',
                  fontSize: '0.82rem',
                }}>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>将保存为草稿，需要修复后才能运行</div>
                  {validationErrors.map((err, i) => (
                    <div key={i}>{err}</div>
                  ))}
                </div>
              )}

              <div>
                <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>
                  工作流计划
                </div>
                <div style={{
                  padding: 12,
                  background: 'var(--bg-tertiary)',
                  borderRadius: 8,
                  whiteSpace: 'pre-wrap',
                  fontSize: '0.85rem',
                  lineHeight: 1.6,
                }}>
                  {preview.plan_text || '无计划说明'}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>
                  节点
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {(workflow.nodes || []).map(node => (
                    <div key={node.id} style={{
                      padding: '8px 10px',
                      background: 'var(--bg-tertiary)',
                      borderRadius: 6,
                      fontSize: '0.8rem',
                    }}>
                      <strong>{node.id}</strong>
                      <span style={{ color: 'var(--text-muted)' }}> / {node.type}</span>
                      <div style={{ marginTop: 4, color: 'var(--text-muted)' }}>
                        inputs: {portList(node.inputs || nodesById.get(node.id)?.inputs)}
                      </div>
                      <div style={{ marginTop: 2, color: 'var(--text-muted)' }}>
                        outputs: {portList(node.outputs || nodesById.get(node.id)?.outputs)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>
                  连线
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {(workflow.edges || []).length === 0 && (
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>暂无连线</div>
                  )}
                  {(workflow.edges || []).map((edge, i) => (
                    <div key={`${edge.source}-${edge.target}-${i}`} style={{
                      padding: '8px 10px',
                      background: 'var(--bg-tertiary)',
                      borderRadius: 6,
                      fontSize: '0.8rem',
                    }}>
                      {edge.source}.{edge.source_handle || edge.sourceHandle || '?'} {'->'} {edge.target}.{edge.target_handle || edge.targetHandle || '?'}
                    </div>
                  ))}
                </div>
              </div>
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
            onClick={handleConfirm}
            disabled={saving || !preview?.workflow}
          >
            {saving ? '保存中...' : validationErrors.length ? '保存为草稿' : '创建工作流'}
          </button>
        </div>
      </div>
    </div>
  )
}
