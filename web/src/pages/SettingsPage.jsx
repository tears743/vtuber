import { useEffect, useState } from 'react'
import { api } from '../api'

export function SettingsPage() {
  const [models, setModels] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)

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
  }

  const handleAdd = async (e) => {
    e.preventDefault()
    const form = new FormData(e.target)
    const data = {
      name: form.get('name'),
      base_url: form.get('base_url'),
      api_key: form.get('api_key'),
      model: form.get('model'),
      context_length: parseInt(form.get('context_length')) || 128000,
      max_output_tokens: parseInt(form.get('max_output_tokens')) || 8192,
      capabilities: form.get('capabilities')?.split(',').map(s => s.trim()) || ['text'],
      note: form.get('note') || '',
    }
    try {
      await api.createModel(data)
      setShowAdd(false)
      const updated = await api.listModels()
      setModels(updated)
    } catch (e) {
      alert('添加失败: ' + e.message)
    }
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
                <button className="btn btn-danger" onClick={() => handleDelete(m.name)}>删除</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {showAdd ? (
        <form onSubmit={handleAdd} className="card" style={{ padding: 24, marginTop: 20 }}>
          <h3 style={{ marginBottom: 16 }}>添加模型</h3>
          <div className="panel-body">
            <div className="form-group">
              <label className="form-label">名称 (唯一标识)</label>
              <input name="name" className="form-input" required placeholder="e.g. gpt-4o" />
            </div>
            <div className="form-group">
              <label className="form-label">Base URL</label>
              <input name="base_url" className="form-input" required placeholder="https://api.openai.com/v1" />
            </div>
            <div className="form-group">
              <label className="form-label">API Key</label>
              <input name="api_key" type="password" className="form-input" required />
            </div>
            <div className="form-group">
              <label className="form-label">Model ID</label>
              <input name="model" className="form-input" required placeholder="gpt-4o" />
            </div>
            <div className="form-group">
              <label className="form-label">Context Length</label>
              <input name="context_length" type="number" className="form-input" defaultValue={128000} />
            </div>
            <div className="form-group">
              <label className="form-label">Max Output Tokens</label>
              <input name="max_output_tokens" type="number" className="form-input" defaultValue={8192} />
            </div>
            <div className="form-group">
              <label className="form-label">能力标签 (逗号分隔)</label>
              <input name="capabilities" className="form-input" defaultValue="text" placeholder="text, vision, video" />
            </div>
            <div className="form-group">
              <label className="form-label">备注</label>
              <input name="note" className="form-input" placeholder="可选描述" />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
            <button type="submit" className="btn btn-primary">保存</button>
            <button type="button" className="btn btn-ghost" onClick={() => setShowAdd(false)}>取消</button>
          </div>
        </form>
      ) : (
        <button className="btn btn-primary" style={{ marginTop: 20 }} onClick={() => setShowAdd(true)}>
          + 添加模型
        </button>
      )}
    </div>
  )
}
