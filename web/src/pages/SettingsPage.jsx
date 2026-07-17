import { useEffect, useState } from 'react'
import { api } from '../api'

export function SettingsPage() {
  const [models, setModels] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [editingModel, setEditingModel] = useState(null)

  useEffect(() => {
    api.listModels()
      .then(setModels)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const handleTest = async (id) => {
    const result = await api.testModel(id)
    alert(result.status === 'ok' ? `✅ ${result.message}` : `❌ ${result.message}`)
  }

  const handleDelete = async (id) => {
    if (!confirm(`确定删除模型 "${id}"?`)) return
    await api.deleteModel(id)
    setModels(prev => prev.filter(m => m.name !== id))
    if (editingModel?.name === id) setEditingModel(null)
  }

  const refreshModels = async () => {
    const updated = await api.listModels()
    setModels(updated)
  }

  const closeForm = () => {
    setShowAdd(false)
    setEditingModel(null)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const form = new FormData(e.target)
    const apiKey = form.get('api_key')?.trim()
    const data = {
      base_url: form.get('base_url'),
      model: form.get('model'),
      context_length: parseInt(form.get('context_length')) || 128000,
      max_output_tokens: parseInt(form.get('max_output_tokens')) || 8192,
      capabilities: form.getAll('capabilities') || [],
      note: form.get('note') || '',
    }
    if (apiKey) data.api_key = apiKey

    try {
      if (editingModel) {
        await api.updateModel(editingModel.name, data)
      } else {
        await api.createModel({ ...data, name: form.get('name') })
      }
      closeForm()
      await refreshModels()
    } catch (error) {
      alert(`${editingModel ? '保存' : '添加'}失败: ${error.message}`)
    }
  }

  const openAddForm = () => {
    setEditingModel(null)
    setShowAdd(true)
  }

  const openEditForm = (model) => {
    setShowAdd(false)
    setEditingModel(model)
  }

  if (loading) return <div className="page-workflows"><p>加载中...</p></div>

  return (
    <div className="page-workflows">
      <h1 className="page-title">⚙️ 全局设置 — 模型管理</h1>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {models.map(m => (
          <div key={m.name} className="card" style={{ padding: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: '1rem' }}>{m.name}</div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 4 }}>{m.base_url}</div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: 4 }}>
                  {m.capabilities?.map(c => (
                    <span key={c} style={{
                      padding: '2px 8px',
                      background: 'rgba(99,102,241,0.12)',
                      borderRadius: 4,
                      marginRight: 6,
                      fontSize: '0.7rem',
                    }}>{c}</span>
                  ))}
                  {m.note && <span style={{ marginLeft: 8, color: 'var(--text-muted)' }}>{m.note}</span>}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-success" onClick={() => handleTest(m.name)}>测试</button>
                <button className="btn btn-ghost" onClick={() => openEditForm(m)}>编辑</button>
                <button className="btn btn-danger" onClick={() => handleDelete(m.name)}>删除</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {showAdd || editingModel ? (
        <form
          key={editingModel?.name || 'new-model'}
          onSubmit={handleSubmit}
          className="card"
          style={{ padding: 24, marginTop: 20 }}
        >
          <h3 style={{ marginBottom: 16 }}>{editingModel ? `编辑模型：${editingModel.name}` : '添加模型'}</h3>
          <div className="panel-body">
            <div className="form-group">
              <label className="form-label">名称 (唯一标识)</label>
              <input
                name="name"
                className="form-input"
                required
                disabled={Boolean(editingModel)}
                defaultValue={editingModel?.name || ''}
                placeholder="e.g. gpt-4o"
              />
            </div>
            <div className="form-group">
              <label className="form-label">Base URL</label>
              <input
                name="base_url"
                className="form-input"
                required
                defaultValue={editingModel?.base_url || ''}
                placeholder="https://api.openai.com/v1"
              />
            </div>
            <div className="form-group">
              <label className="form-label">API Key</label>
              <input
                name="api_key"
                type="password"
                className="form-input"
                required={!editingModel}
                autoComplete="new-password"
                placeholder={editingModel ? '留空则保留当前 API Key' : ''}
              />
            </div>
            <div className="form-group">
              <label className="form-label">Model ID</label>
              <input
                name="model"
                className="form-input"
                required
                defaultValue={editingModel?.model || ''}
                placeholder="gpt-4o"
              />
            </div>
            <div className="form-group">
              <label className="form-label">Context Length</label>
              <input
                name="context_length"
                type="number"
                min="1"
                className="form-input"
                defaultValue={editingModel?.context_length || 128000}
              />
            </div>
            <div className="form-group">
              <label className="form-label">Max Output Tokens</label>
              <input
                name="max_output_tokens"
                type="number"
                min="1"
                className="form-input"
                defaultValue={editingModel?.max_output_tokens || 8192}
              />
            </div>
            <div className="form-group">
              <label className="form-label">能力标签</label>
              <div style={{ display: 'flex', gap: 20, alignItems: 'center', padding: '8px 0' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <input type="checkbox" name="capabilities" value="coding" defaultChecked={editingModel?.capabilities?.includes('coding')} /> 编码
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <input type="checkbox" name="capabilities" value="multimodal" defaultChecked={editingModel?.capabilities?.includes('multimodal')} /> 多模态
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <input type="checkbox" name="capabilities" value="text" defaultChecked={editingModel?.capabilities?.includes('text')} /> 纯文本
                </label>
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">备注</label>
              <input name="note" className="form-input" defaultValue={editingModel?.note || ''} placeholder="可选描述" />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
            <button type="submit" className="btn btn-primary">保存</button>
            <button type="button" className="btn btn-ghost" onClick={closeForm}>取消</button>
          </div>
        </form>
      ) : (
        <button className="btn btn-primary" style={{ marginTop: 20 }} onClick={openAddForm}>
          + 添加模型
        </button>
      )}
    </div>
  )
}
