import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

export function WorkflowList() {
  const [workflows, setWorkflows] = useState([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [toast, setToast] = useState(null) // {type: 'error'|'success', msg: ''}
  const navigate = useNavigate()

  useEffect(() => {
    api.listWorkflows()
      .then(setWorkflows)
      .catch(e => showToast('error', '加载失败: ' + e.message))
      .finally(() => setLoading(false))
  }, [])

  const showToast = (type, msg) => {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 3000)
  }

  const handleCreate = async () => {
    const name = newName.trim() || '新建工作流'
    try {
      const wf = await api.createWorkflow({ name, nodes: [], edges: [] })
      navigate(`/workflow/${wf.id}`)
    } catch (e) {
      showToast('error', '创建失败: ' + e.message)
    }
  }

  const handleDelete = async (e, id) => {
    e.stopPropagation()
    try {
      await api.deleteWorkflow(id)
      setWorkflows(prev => prev.filter(w => w.id !== id))
      showToast('success', '已删除')
    } catch (e) {
      showToast('error', '删除失败: ' + e.message)
    }
  }

  if (loading) return <div className="page-workflows"><p>加载中...</p></div>

  return (
    <div className="page-workflows">
      <h1 className="page-title">工作流</h1>
      <div className="workflow-grid">
        {workflows.map(wf => (
          <div
            key={wf.id}
            className="card workflow-card animate-in"
            onClick={() => navigate(`/workflow/${wf.id}`)}
          >
            <div className="workflow-card-name">{wf.name}</div>
            <div className="workflow-card-meta">
              <span>📦 {wf.node_count} 节点</span>
              <span>📅 {wf.updated_at?.slice(0, 10) || '—'}</span>
            </div>
            <button
              className="btn btn-danger"
              style={{ marginTop: 12 }}
              onClick={(e) => handleDelete(e, wf.id)}
            >
              删除
            </button>
          </div>
        ))}

        {creating ? (
          <div className="card workflow-card-new" style={{ display: 'flex', flexDirection: 'column', gap: 12, cursor: 'default' }}>
            <input
              className="form-input"
              autoFocus
              placeholder="工作流名称"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') handleCreate()
                if (e.key === 'Escape') { setCreating(false); setNewName('') }
              }}
            />
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn-primary" style={{ flex: 1 }} onClick={handleCreate}>创建</button>
              <button className="btn" style={{ flex: 1 }} onClick={() => { setCreating(false); setNewName('') }}>取消</button>
            </div>
          </div>
        ) : (
          <div className="card workflow-card-new" onClick={() => setCreating(true)}>
            <span>+ 新建工作流</span>
          </div>
        )}
      </div>

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
