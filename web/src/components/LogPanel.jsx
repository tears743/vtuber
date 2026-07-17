/**
 * LogPanel — 底部日志面板
 * 实时显示执行日志，支持按节点过滤、级别筛选
 */
import { useEffect, useRef, useState } from 'react'

const DEFAULT_PANEL_HEIGHT = 220
const MIN_PANEL_HEIGHT = 120
const PANEL_HEIGHT_STORAGE_KEY = 'videofactory.logPanelHeight'

function clampPanelHeight(height) {
  const viewportHeight = typeof window === 'undefined' ? 900 : window.innerHeight
  const maxHeight = Math.max(MIN_PANEL_HEIGHT, Math.floor(viewportHeight * 0.7))
  return Math.min(maxHeight, Math.max(MIN_PANEL_HEIGHT, height))
}

const LEVEL_COLORS = {
  DEBUG: 'var(--text-muted)',
  INFO: 'var(--text-secondary)',
  WARNING: 'var(--accent-amber)',
  ERROR: 'var(--accent-rose)',
  CRITICAL: 'var(--accent-rose)',
}

export function LogPanel({ logs, isExpanded, onToggle }) {
  const logsEndRef = useRef(null)
  const resizeStartRef = useRef(null)
  const [filter, setFilter] = useState('')  // 节点 ID 过滤
  const [levelFilter, setLevelFilter] = useState('INFO')  // 级别过滤
  const [autoScroll, setAutoScroll] = useState(true)
  const [isResizing, setIsResizing] = useState(false)
  const [panelHeight, setPanelHeight] = useState(() => {
    const savedHeight = Number(window.localStorage.getItem(PANEL_HEIGHT_STORAGE_KEY))
    return clampPanelHeight(Number.isFinite(savedHeight) && savedHeight > 0 ? savedHeight : DEFAULT_PANEL_HEIGHT)
  })

  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, autoScroll])

  useEffect(() => {
    window.localStorage.setItem(PANEL_HEIGHT_STORAGE_KEY, String(panelHeight))
  }, [panelHeight])

  useEffect(() => {
    const handleViewportResize = () => setPanelHeight(current => clampPanelHeight(current))
    window.addEventListener('resize', handleViewportResize)
    return () => window.removeEventListener('resize', handleViewportResize)
  }, [])

  useEffect(() => {
    if (!isResizing) return undefined

    const handlePointerMove = (event) => {
      const start = resizeStartRef.current
      if (!start) return
      setPanelHeight(clampPanelHeight(start.height + start.y - event.clientY))
    }
    const stopResizing = () => setIsResizing(false)

    document.body.classList.add('is-resizing-log-panel')
    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', stopResizing)
    window.addEventListener('pointercancel', stopResizing)
    window.addEventListener('blur', stopResizing)

    return () => {
      document.body.classList.remove('is-resizing-log-panel')
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', stopResizing)
      window.removeEventListener('pointercancel', stopResizing)
      window.removeEventListener('blur', stopResizing)
      resizeStartRef.current = null
    }
  }, [isResizing])

  const startResizing = (event) => {
    if (event.button !== 0) return
    event.preventDefault()
    resizeStartRef.current = { y: event.clientY, height: panelHeight }
    setIsResizing(true)
  }

  const handleResizeKeyDown = (event) => {
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
    event.preventDefault()
    const step = event.shiftKey ? 64 : 24
    setPanelHeight(current => clampPanelHeight(current + (event.key === 'ArrowUp' ? step : -step)))
  }

  const LEVEL_ORDER = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3, CRITICAL: 4 }

  const filteredLogs = logs.filter(l => {
    // 级别筛选
    const logLevel = LEVEL_ORDER[l.level] ?? 1
    const minLevel = LEVEL_ORDER[levelFilter] ?? 0
    if (logLevel < minLevel) return false
    // 节点筛选
    if (filter && l.node_id !== filter && l.level !== 'ERROR') return false
    return true
  })

  // 获取所有出现过的节点 ID
  const nodeIds = [...new Set(logs.map(l => l.node_id).filter(Boolean))]

  if (!isExpanded) {
    return (
      <div className="log-panel-collapsed" onClick={onToggle}>
        <span className="log-panel-toggle">▲ 日志</span>
        <span className="log-panel-count">
          {logs.length} 条
          {logs.filter(l => l.level === 'ERROR').length > 0 && (
            <span className="log-error-badge">
              {logs.filter(l => l.level === 'ERROR').length} 错误
            </span>
          )}
        </span>
      </div>
    )
  }

  return (
    <div className="log-panel" style={{ height: panelHeight }}>
      <div
        className={`log-panel-resize-handle${isResizing ? ' is-resizing' : ''}`}
        role="separator"
        aria-label="调整日志面板高度"
        aria-orientation="horizontal"
        tabIndex={0}
        title="拖动调整日志面板高度"
        onPointerDown={startResizing}
        onKeyDown={handleResizeKeyDown}
      />
      {/* Header */}
      <div className="log-panel-header">
        <div className="log-panel-header-left">
          <span className="log-panel-toggle" onClick={onToggle}>▼ 日志</span>
          <select
            className="log-filter-select"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="">全部节点</option>
            {nodeIds.map(nid => (
              <option key={nid} value={nid}>{nid}</option>
            ))}
          </select>
          <select
            className="log-filter-select"
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value)}
          >
            <option value="DEBUG">DEBUG+</option>
            <option value="INFO">INFO+</option>
            <option value="WARNING">WARN+</option>
            <option value="ERROR">ERROR</option>
          </select>
        </div>
        <div className="log-panel-header-right">
          <label className="log-autoscroll">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
            />
            <span>自动滚动</span>
          </label>
          <span className="log-panel-count">{filteredLogs.length} 条</span>
        </div>
      </div>

      {/* Log entries */}
      <div className="log-panel-body">
        {filteredLogs.map((log, i) => (
          <div key={i} className={`log-entry log-${log.level?.toLowerCase()}`}>
            <span className="log-time">
              {new Date(log.timestamp * 1000).toLocaleTimeString('zh-CN', { hour12: false })}
            </span>
            <span className="log-level" style={{ color: LEVEL_COLORS[log.level] }}>
              {log.level?.slice(0, 4)}
            </span>
            {log.node_id && <span className="log-node">[{log.node_id}]</span>}
            <span className="log-message">{log.message}</span>
          </div>
        ))}
        <div ref={logsEndRef} />
      </div>
    </div>
  )
}
