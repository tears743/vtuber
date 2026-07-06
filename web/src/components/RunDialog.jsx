/**
 * RunDialog — 运行参数弹窗
 * 点击"运行"按钮后弹出，设置运行日期等参数
 */
import { useState } from 'react'
import { api } from '../api'

export function RunDialog({ onConfirm, onCancel }) {
  const today = new Date().toISOString().slice(0, 10)
  const [date, setDate] = useState(today)
  const [forceNoCache, setForceNoCache] = useState(false)
  const [clearing, setClearing] = useState(false)

  const handleClearCache = async () => {
    if (!confirm(`确认清除 ${date} 的所有缓存？(日志除外)`)) return
    setClearing(true)
    try {
      const res = await api.clearCache({ date })
      alert(`已清除: ${res.cleared?.join(', ') || '无'}`)
    } catch (e) {
      alert(`清除失败: ${e.message}`)
    }
    setClearing(false)
  }

  return (
    <div className="prompt-editor-overlay" onClick={onCancel}>
      <div className="run-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="run-dialog-header">
          <span>▶️ 运行工作流</span>
        </div>
        <div className="run-dialog-body">
          <div className="form-group">
            <label className="form-label">运行日期</label>
            <input
              className="form-input"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 4 }}>
              指定采集/处理哪天的数据，默认今天
            </span>
          </div>
          <div className="form-group" style={{ marginTop: 12 }}>
            <label className="form-checkbox">
              <input
                type="checkbox"
                checked={forceNoCache}
                onChange={(e) => setForceNoCache(e.target.checked)}
              />
              <span>忽略缓存，全部重新执行</span>
            </label>
          </div>
        </div>
        <div className="run-dialog-footer">
          <button
            className="btn btn-ghost"
            onClick={handleClearCache}
            disabled={clearing}
            style={{ marginRight: 'auto' }}
          >
            {clearing ? '清除中...' : '🗑️ 清除缓存'}
          </button>
          <button className="btn btn-ghost" onClick={onCancel}>取消</button>
          <button className="btn btn-primary" onClick={() => onConfirm({ date, forceNoCache })}>
            ▶️ 开始执行
          </button>
        </div>
      </div>
    </div>
  )
}
