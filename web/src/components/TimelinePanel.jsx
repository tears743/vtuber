/**
 * 内嵌时间轴面板 — 用于 WorkflowEditor 内部
 * 可折叠，脚本产出后自动展开
 * 支持鼠标滚轮缩放，visual 按 type 分轨显示
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { api } from '../api'

const TRACK_COLORS = {
  voice: '#4ecdc4',
  'visual:video_clip': '#ff6b6b',
  'visual:image': '#e17055',
  'visual:remotion': '#fd79a8',
  live2d: '#a29bfe',
  overlay: '#fdcb6e',
}

const TRACK_LABELS = {
  voice: '🎙️ Voice',
  'visual:video_clip': '🎬 视频素材',
  'visual:image': '🖼️ 图片素材',
  'visual:remotion': '✨ Remotion',
  live2d: '🧑 Live2D',
  overlay: '📝 Overlay',
}

function formatTime(ms) {
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}:${String(sec).padStart(2, '0')}`
}

function buildTooltip(item, trackName) {
  const lines = [
    `⏱ ${formatTime(item.start_ms)} - ${formatTime(item.start_ms + item.duration_ms)} (${(item.duration_ms/1000).toFixed(1)}s)`,
  ]
  if (item.text) lines.push(`📝 ${item.text}`)
  if (item.type) lines.push(`🏷 type: ${item.type}`)
  if (item.source) {
    const parts = item.source.replace(/\\/g, '/').split('/')
    const short = parts.slice(-2).join('/')
    lines.push(`📂 source: ${short}`)
  }
  if (item.component) lines.push(`🧩 component: ${item.component}`)
  if (item.play_audio) lines.push(`🔊 play_audio: true`)
  if (item.time_range) lines.push(`🎞 time_range: [${item.time_range.map(v => typeof v === 'number' ? v.toFixed(1) : v).join(', ')}]`)
  if (item.action) lines.push(`⚡ action: ${item.action}`)
  return lines.join('\n')
}

function MiniTrackItem({ item, pxPerMs, trackName }) {
  const left = item.start_ms * pxPerMs
  const width = Math.max(item.duration_ms * pxPerMs, 2)
  const color = TRACK_COLORS[trackName] || '#888'
  const isPlayAudio = item.play_audio

  const label = trackName === 'voice'
    ? (item.text || '').slice(0, 20) || '(silence)'
    : trackName.startsWith('visual:')
      ? (item.source || item.component || item.type || '').toString().split(/[\\/]/).pop()?.slice(0, 15)
      : ''

  return (
    <div
      className="timeline-item"
      style={{
        left: `${left}px`,
        width: `${width}px`,
        backgroundColor: isPlayAudio ? '#d63031' : color,
        opacity: item.text === '' && trackName === 'voice' ? 0.4 : 1,
      }}
      title={buildTooltip(item, trackName)}
    >
      <span className="timeline-item-label">{label}</span>
    </div>
  )
}

function MiniRuler({ totalMs, pxPerMs }) {
  const marks = []
  // 动态步长
  const totalPx = totalMs * pxPerMs
  let step = 30000
  if (pxPerMs > 0.06) step = 10000
  if (pxPerMs > 0.15) step = 5000
  if (pxPerMs < 0.02) step = 60000

  for (let ms = 0; ms <= totalMs; ms += step) {
    marks.push(
      <div key={ms} className="time-mark" style={{ left: `${ms * pxPerMs}px` }}>
        <div className="time-mark-line" />
        <span className="time-mark-label">{formatTime(ms)}</span>
      </div>
    )
  }
  return <div className="time-ruler mini">{marks}</div>
}

// 把 visual 轨按 type 拆分成子轨
function splitVisualTracks(visualItems) {
  const sub = {
    'visual:video_clip': [],
    'visual:image': [],
    'visual:remotion': [],
  }
  for (const item of (visualItems || [])) {
    const t = item.type
    if (t === 'video_clip') sub['visual:video_clip'].push(item)
    else if (t === 'image') sub['visual:image'].push(item)
    else sub['visual:remotion'].push(item) // remotion + others
  }
  return sub
}

export function TimelinePanel({ isExpanded, onToggle, runDate }) {
  const [dates, setDates] = useState([])
  const [selectedDate, setSelectedDate] = useState('')
  const [selectedScript, setSelectedScript] = useState('')
  const [showAligned, setShowAligned] = useState(true)
  const [compareData, setCompareData] = useState(null)
  const [scriptData, setScriptData] = useState(null)
  const [zoom, setZoom] = useState(0.5)
  const scrollRef = useRef(null)

  // 鼠标滚轮缩放（不需要 Ctrl）
  const handleWheel = useCallback((e) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? -0.1 : 0.1
    setZoom(z => Math.max(0.1, Math.min(4, z + delta)))
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.addEventListener('wheel', handleWheel, { passive: false })
    return () => el.removeEventListener('wheel', handleWheel)
  }, [handleWheel, isExpanded])

  // 加载日期列表
  useEffect(() => {
    api.listScriptDates().then(data => {
      setDates(data)
      const target = runDate || (data.length > 0 ? data[0].date : '')
      setSelectedDate(target)
      const d = data.find(x => x.date === target) || data[0]
      if (d && d.scripts.length > 0) setSelectedScript(d.scripts[0])
    }).catch(() => {})
  }, [runDate])

  // runDate 变化时自动切换
  useEffect(() => {
    if (runDate && dates.length > 0) {
      setSelectedDate(runDate)
      const d = dates.find(x => x.date === runDate)
      if (d && d.scripts.length > 0 && !d.scripts.includes(selectedScript)) {
        setSelectedScript(d.scripts[0])
      }
    }
  }, [runDate, dates])

  // 加载脚本
  useEffect(() => {
    if (!selectedDate || !selectedScript) return
    api.getScriptCompare(selectedDate, selectedScript)
      .then(data => {
        setCompareData(data)
        setScriptData(showAligned && data.aligned ? data.aligned : data.original)
      })
      .catch(() => setScriptData(null))
  }, [selectedDate, selectedScript])

  // 切换对齐
  useEffect(() => {
    if (!compareData) return
    setScriptData(showAligned && compareData.aligned ? compareData.aligned : compareData.original)
  }, [showAligned, compareData])

  // 构建轨道数据（visual 拆分为子轨）
  const displayTracks = useMemo(() => {
    const tracks = scriptData?.tracks || {}
    const result = {}
    
    // voice
    if (tracks.voice?.length) result.voice = tracks.voice
    
    // visual 拆分
    const visualSubs = splitVisualTracks(tracks.visual)
    for (const [key, items] of Object.entries(visualSubs)) {
      if (items.length > 0) result[key] = items
    }
    
    // live2d
    if (tracks.live2d?.length) result.live2d = tracks.live2d
    
    // overlay
    if (tracks.overlay?.length) result.overlay = tracks.overlay
    
    return result
  }, [scriptData])

  const totalMs = scriptData?.total_duration_ms || 0
  const pxPerMs = 0.04 * zoom
  const totalWidth = totalMs * pxPerMs

  const currentScripts = dates.find(d => d.date === selectedDate)?.scripts || []

  if (!isExpanded) {
    return (
      <div className="timeline-panel-collapsed" onClick={onToggle}>
        <span>🎬 时间轴 {scriptData ? `(${selectedScript} · ${formatTime(totalMs)})` : ''}</span>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>点击展开</span>
      </div>
    )
  }

  return (
    <div className="timeline-panel">
      {/* 面板头 */}
      <div className="timeline-panel-header">
        <div className="timeline-panel-left">
          <span className="timeline-panel-title">🎬 时间轴</span>
          
          <select
            value={selectedDate}
            onChange={e => {
              setSelectedDate(e.target.value)
              const d = dates.find(x => x.date === e.target.value)
              if (d && d.scripts.length > 0) setSelectedScript(d.scripts[0])
            }}
            className="timeline-mini-select"
          >
            {dates.map(d => <option key={d.date} value={d.date}>{d.date}</option>)}
          </select>

          {currentScripts.map(s => (
            <button
              key={s}
              className={`script-tab mini ${s === selectedScript ? 'active' : ''}`}
              onClick={() => setSelectedScript(s)}
            >
              {s}
            </button>
          ))}

          <label className="align-toggle mini">
            <input
              type="checkbox"
              checked={showAligned}
              onChange={e => setShowAligned(e.target.checked)}
              disabled={!compareData?.aligned}
            />
            对齐后
          </label>
        </div>

        <div className="timeline-panel-right">
          {totalMs > 0 && <span className="timeline-panel-info">{formatTime(totalMs)}</span>}
          <div className="zoom-control mini">
            <button onClick={() => setZoom(z => Math.max(0.1, z - 0.15))}>−</button>
            <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)' }}>{Math.round(zoom * 100)}%</span>
            <button onClick={() => setZoom(z => Math.min(4, z + 0.15))}>+</button>
          </div>
          <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', opacity: 0.5 }}>Ctrl+滚轮缩放</span>
          <button className="timeline-panel-close" onClick={onToggle}>▼</button>
        </div>
      </div>

      {/* 轨道内容 */}
      {scriptData ? (
        <div className="timeline-panel-body">
          <div className="timeline-tracks-container compact">
            <div className="track-labels compact">
              {Object.keys(displayTracks).map(trackName => {
                const items = displayTracks[trackName]
                if (!items || items.length === 0) return null
                return (
                  <div key={trackName} className="track-label compact">
                    <span className="track-label-dot" style={{ background: TRACK_COLORS[trackName] || '#888' }} />
                    {TRACK_LABELS[trackName] || trackName}
                    <span className="track-count">{items.length}</span>
                  </div>
                )
              })}
            </div>

            <div className="timeline-scroll compact" ref={scrollRef}>
              <MiniRuler totalMs={totalMs} pxPerMs={pxPerMs} />
              <div className="tracks-area" style={{ width: `${totalWidth}px` }}>
                {Object.keys(displayTracks).map(trackName => {
                  const items = displayTracks[trackName]
                  if (!items || items.length === 0) return null
                  return (
                    <div key={trackName} className="track-row compact">
                      {items.map((item, i) => (
                        <MiniTrackItem key={i} item={item} pxPerMs={pxPerMs} trackName={trackName} />
                      ))}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="timeline-panel-empty">暂无脚本数据</div>
      )}
    </div>
  )
}
