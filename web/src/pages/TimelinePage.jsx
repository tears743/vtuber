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

function TrackItem({ item, pxPerMs, trackName, onClick }) {
  const left = item.start_ms * pxPerMs
  const width = Math.max(item.duration_ms * pxPerMs, 2)
  const color = TRACK_COLORS[trackName] || '#888'
  
  const isPlayAudio = item.play_audio
  const label = trackName === 'voice'
    ? (item.text || '').slice(0, 20) || '(silence)'
    : trackName.startsWith('visual:')
      ? (item.source || item.component || item.type || '').toString().split(/[\\/]/).pop()?.slice(0, 20)
      : item.type || item.action || ''

  return (
    <div
      className={`timeline-item ${isPlayAudio ? 'play-audio' : ''}`}
      style={{
        left: `${left}px`,
        width: `${width}px`,
        backgroundColor: isPlayAudio ? '#d63031' : color,
        opacity: item.text === '' && trackName === 'voice' ? 0.5 : 1,
      }}
      title={buildTooltip(item, trackName)}
      onClick={() => onClick && onClick(item)}
    >
      <span className="timeline-item-label">{label}</span>
    </div>
  )
}

function TimeRuler({ totalMs, pxPerMs }) {
  const marks = []
  let step = 10000
  if (pxPerMs > 0.15) step = 5000
  if (pxPerMs < 0.04) step = 30000
  if (pxPerMs < 0.02) step = 60000

  for (let ms = 0; ms <= totalMs; ms += step) {
    marks.push(
      <div key={ms} className="time-mark" style={{ left: `${ms * pxPerMs}px` }}>
        <div className="time-mark-line" />
        <span className="time-mark-label">{formatTime(ms)}</span>
      </div>
    )
  }
  return <div className="time-ruler">{marks}</div>
}

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
    else sub['visual:remotion'].push(item)
  }
  return sub
}

export function TimelinePage() {
  const [dates, setDates] = useState([])
  const [selectedDate, setSelectedDate] = useState('')
  const [selectedScript, setSelectedScript] = useState('')
  const [showAligned, setShowAligned] = useState(true)
  const [scriptData, setScriptData] = useState(null)
  const [compareData, setCompareData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [selectedItem, setSelectedItem] = useState(null)
  const [zoom, setZoom] = useState(1)
  const scrollRef = useRef(null)

  // 鼠标滚轮缩放（不需要 Ctrl）
  const handleWheel = useCallback((e) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? -0.15 : 0.15
    setZoom(z => Math.max(0.1, Math.min(6, z + delta)))
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.addEventListener('wheel', handleWheel, { passive: false })
    return () => el.removeEventListener('wheel', handleWheel)
  }, [handleWheel])

  // 加载日期列表
  useEffect(() => {
    api.listScriptDates().then(data => {
      setDates(data)
      if (data.length > 0) {
        setSelectedDate(data[0].date)
        if (data[0].scripts.length > 0) {
          setSelectedScript(data[0].scripts[0])
        }
      }
    }).catch(console.error)
  }, [])

  // 加载脚本
  useEffect(() => {
    if (!selectedDate || !selectedScript) return
    setLoading(true)
    
    api.getScriptCompare(selectedDate, selectedScript)
      .then(data => {
        setCompareData(data)
        setScriptData(showAligned && data.aligned ? data.aligned : data.original)
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [selectedDate, selectedScript])

  // 切换对齐前后
  useEffect(() => {
    if (!compareData) return
    setScriptData(showAligned && compareData.aligned ? compareData.aligned : compareData.original)
  }, [showAligned, compareData])

  // 构建分轨数据
  const displayTracks = useMemo(() => {
    const tracks = scriptData?.tracks || {}
    const result = {}
    if (tracks.voice?.length) result.voice = tracks.voice
    const visualSubs = splitVisualTracks(tracks.visual)
    for (const [key, items] of Object.entries(visualSubs)) {
      if (items.length > 0) result[key] = items
    }
    if (tracks.live2d?.length) result.live2d = tracks.live2d
    if (tracks.overlay?.length) result.overlay = tracks.overlay
    return result
  }, [scriptData])

  const totalMs = scriptData?.total_duration_ms || 0
  const pxPerMs = (0.08 * zoom)
  const totalWidth = totalMs * pxPerMs

  const currentScripts = dates.find(d => d.date === selectedDate)?.scripts || []

  return (
    <div className="timeline-page">
      {/* 顶部控制栏 */}
      <div className="timeline-controls">
        <div className="timeline-selectors">
          <select value={selectedDate} onChange={e => {
            setSelectedDate(e.target.value)
            const d = dates.find(x => x.date === e.target.value)
            if (d && d.scripts.length > 0) setSelectedScript(d.scripts[0])
          }}>
            {dates.map(d => (
              <option key={d.date} value={d.date}>{d.date}</option>
            ))}
          </select>

          <div className="script-tabs">
            {currentScripts.map(s => (
              <button
                key={s}
                className={`script-tab ${s === selectedScript ? 'active' : ''}`}
                onClick={() => setSelectedScript(s)}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <div className="timeline-actions">
          <label className="align-toggle">
            <input
              type="checkbox"
              checked={showAligned}
              onChange={e => setShowAligned(e.target.checked)}
              disabled={!compareData?.aligned}
            />
            对齐后
          </label>
          
          <div className="zoom-control">
            <button onClick={() => setZoom(z => Math.max(0.1, z - 0.25))}>−</button>
            <span>{Math.round(zoom * 100)}%</span>
            <button onClick={() => setZoom(z => Math.min(6, z + 0.25))}>+</button>
          </div>

          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>滚轮缩放</span>

          <div className="timeline-info">
            {totalMs > 0 && <span>总时长: {formatTime(totalMs)} ({(totalMs/1000).toFixed(0)}s)</span>}
          </div>
        </div>
      </div>

      {/* 时间轴主体 */}
      {loading ? (
        <div className="timeline-loading">加载中...</div>
      ) : !scriptData ? (
        <div className="timeline-empty">选择一个脚本查看时间轴</div>
      ) : (
        <div className="timeline-body">
          <div className="timeline-tracks-container">
            {/* 轨道标签 */}
            <div className="track-labels">
              {Object.keys(displayTracks).map(trackName => {
                const items = displayTracks[trackName]
                if (!items || items.length === 0) return null
                return (
                  <div key={trackName} className="track-label">
                    <span className="track-label-dot" style={{ background: TRACK_COLORS[trackName] || '#888' }} />
                    {TRACK_LABELS[trackName] || trackName}
                    <span className="track-count">{items.length}</span>
                  </div>
                )
              })}
            </div>

            {/* 轨道内容（可横向滚动 + Ctrl滚轮缩放） */}
            <div className="timeline-scroll" ref={scrollRef}>
              <TimeRuler totalMs={totalMs} pxPerMs={pxPerMs} />
              
              <div className="tracks-area" style={{ width: `${totalWidth}px` }}>
                {Object.keys(displayTracks).map(trackName => {
                  const items = displayTracks[trackName]
                  if (!items || items.length === 0) return null
                  return (
                    <div key={trackName} className="track-row">
                      {items.map((item, i) => (
                        <TrackItem
                          key={i}
                          item={item}
                          pxPerMs={pxPerMs}
                          trackName={trackName}
                          onClick={setSelectedItem}
                        />
                      ))}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>

          {/* 属性面板 */}
          {selectedItem && (
            <div className="timeline-inspector">
              <div className="inspector-header">
                <h4>属性</h4>
                <button className="inspector-close" onClick={() => setSelectedItem(null)}>×</button>
              </div>
              <div className="inspector-body">
                <table>
                  <tbody>
                    {Object.entries(selectedItem).map(([key, value]) => (
                      <tr key={key}>
                        <td className="prop-key">{key}</td>
                        <td className="prop-value">
                          {typeof value === 'object' ? JSON.stringify(value) : String(value).slice(0, 100)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
