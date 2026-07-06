import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

export function WorkflowList() {
  const [workflows, setWorkflows] = useState([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    api.listWorkflows()
      .then(setWorkflows)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const handleCreate = async () => {
    const name = prompt('工作流名称:', '新建工作流')
    if (!name) return
    try {
      const wf = await api.createWorkflow({ name, nodes: [], edges: [] })
      navigate(`/workflow/${wf.id}`)
    } catch (e) {
      alert('创建失败: ' + e.message)
    }
  }

  const handleDelete = async (e, id) => {
    e.stopPropagation()
    if (!confirm('确定删除该工作流?')) return
    try {
      await api.deleteWorkflow(id)
      setWorkflows(prev => prev.filter(w => w.id !== id))
    } catch (e) {
      alert('删除失败: ' + e.message)
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
        <div className="card workflow-card-new" onClick={handleCreate}>
          <span>+ 新建工作流</span>
        </div>
      </div>
    </div>
  )
}
