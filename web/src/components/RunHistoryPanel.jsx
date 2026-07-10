/**
 * 运行历史面板 — 显示工作流的运行历史，点击恢复日志和状态
 */
import { useEffect, useState } from 'react'
import { api } from '../api'

export function RunHistoryPanel({ workflowId, currentRunId, refreshKey, onSelectRun, isExpanded, onToggle }) {
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(false)

  // 加载运行历史
  useEffect(() => {
    if (!isExpanded || !workflowId) return
    setLoading(true)
    api.getRunHistory(workflowId)
      .then(res => setHistory(res.runs || []))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [isExpanded, workflowId, currentRunId, refreshKey])

  if (!isExpanded) return null

  const statusIcon = (status) => {
    if (status === 'completed') return '✅'
    if (status === 'running') return '🔄'
    if (status === 'failed') return '❌'
    if (status === 'stopped') return '⏹️'
    return '⏳'
  }

  const statusColor = (status) => {
    if (status === 'completed') return '#34d399'
    if (status === 'running') return '#fbbf24'
    if (status === 'failed') return '#f87171'
    if (status === 'stopped') return '#94a3b8'
    return '#6b7280'
  }

  const formatTime = (ts) => {
    if (!ts) return ''
    const d = new Date(ts * 1000)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  const formatDuration = (start, end) => {
    if (!start || !end) return ''
    const s = end - start
    if (s < 60) return `${s.toFixed(1)}s`
    return `${(s / 60).toFixed(1)}min`
  }

  return (
    <div style={{
      width: 280,
      background: 'var(--bg-secondary)',
      borderLeft: '1px solid var(--border-primary)',
      overflow: 'auto',
      flexShrink: 0,
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '12px 16px',
        borderBottom: '1px solid var(--border-primary)',
        position: 'sticky',
        top: 0,
        background: 'var(--bg-secondary)',
        zIndex: 1,
      }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>运行历史</span>
        <button
          className="btn btn-ghost"
          style={{ padding: '2px 8px', fontSize: 12 }}
          onClick={onToggle}
        >✕</button>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-secondary)' }}>
          加载中...
        </div>
      )}

      {/* Empty */}
      {!loading && history.length === 0 && (
        <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-secondary)' }}>
          暂无运行历史
        </div>
      )}

      {/* History List */}
      {!loading && history.map((run) => (
        <div
          key={run.run_id}
          onClick={() => onSelectRun(run.run_id)}
          style={{
            padding: '10px 16px',
            borderBottom: '1px solid var(--border-primary)',
            cursor: 'pointer',
            transition: 'background 0.15s',
            background: run.run_id === currentRunId ? 'rgba(99,102,241,0.1)' : 'transparent',
          }}
          onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(99,102,241,0.08)'}
          onMouseLeave={(e) => e.currentTarget.style.background = run.run_id === currentRunId ? 'rgba(99,102,241,0.1)' : 'transparent'}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 14 }}>{statusIcon(run.status)}</span>
            <span style={{ fontWeight: 600, fontSize: 13, color: statusColor(run.status) }}>
              {run.status}
            </span>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)', marginLeft: 'auto' }}>
              {formatDuration(run.start_time, run.end_time)}
            </span>
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            {formatTime(run.start_time)}
          </div>
          {run.date && (
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>
              📅 {run.date}
            </div>
          )}
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>
            {Object.keys(run.node_states || {}).length} 节点
          </div>
        </div>
      ))}
    </div>
  )
}
