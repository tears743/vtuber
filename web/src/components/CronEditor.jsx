/**
 * Cron 可视化编辑器
 * 预设模式 + 分字段设置 + 人类可读描述
 */
import { useMemo, useState } from 'react'

// 预设模式
const PRESETS = [
  { label: '每分钟', value: '*/1 * * * *', desc: '每分钟一次' },
  { label: '每 5 分钟', value: '*/5 * * * *', desc: '每 5 分钟一次' },
  { label: '每 15 分钟', value: '*/15 * * * *', desc: '每 15 分钟一次' },
  { label: '每 30 分钟', value: '*/30 * * * *', desc: '每 30 分钟一次' },
  { label: '每小时', value: '0 * * * *', desc: '每小时整点' },
  { label: '每天 8:00', value: '0 8 * * *', desc: '每天早上 8:00' },
  { label: '每天 0:00', value: '0 0 * * *', desc: '每天凌晨 0:00' },
  { label: '每周一 8:00', value: '0 8 * * 1', desc: '每周一早上 8:00' },
  { label: '每月 1 号 8:00', value: '0 8 1 * *', desc: '每月 1 号早上 8:00' },
  { label: '工作日 8:00', value: '0 8 * * 1-5', desc: '周一至周五早上 8:00' },
  { label: '自定义', value: null, desc: '' },
]

// 字段定义
const FIELDS = [
  { key: 'minute', label: '分', range: '0-59', default: '0', help: '* = 每分' },
  { key: 'hour', label: '时', range: '0-23', default: '8', help: '* = 每时' },
  { key: 'day', label: '日', range: '1-31', default: '*', help: '* = 每天' },
  { key: 'month', label: '月', range: '1-12', default: '*', help: '* = 每月' },
  { key: 'weekday', label: '周', range: '0-6', default: '*', help: '* = 每周，0=周日' },
]

// 周几映射
const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

/**
 * 将 cron 表达式解析为分字段
 */
function parseCron(expr) {
  if (!expr) return { minute: '0', hour: '8', day: '*', month: '*', weekday: '*' }
  const parts = expr.trim().split(/\s+/)
  return {
    minute: parts[0] || '0',
    hour: parts[1] || '8',
    day: parts[2] || '*',
    month: parts[3] || '*',
    weekday: parts[4] || '*',
  }
}

/**
 * 将分字段组合为 cron 表达式
 */
function buildCron(fields) {
  return [fields.minute, fields.hour, fields.day, fields.month, fields.weekday].join(' ')
}

/**
 * 生成人类可读的描述
 */
function describeCron(expr) {
  const f = parseCron(expr)

  // 每 N 分钟
  if (f.minute.startsWith('*/') && f.hour === '*' && f.day === '*') {
    const n = f.minute.slice(2)
    return `每 ${n} 分钟`
  }
  // 每小时整点
  if (f.minute === '0' && f.hour === '*' && f.day === '*') {
    return '每小时整点'
  }
  // 每天
  if (f.day === '*' && f.month === '*' && f.weekday === '*') {
    return `每天 ${f.hour.padStart(2, '0')}:${f.minute.padStart(2, '0')}`
  }
  // 工作日
  if (f.weekday === '1-5') {
    return `工作日 ${f.hour.padStart(2, '0')}:${f.minute.padStart(2, '0')}`
  }
  // 每周
  if (f.weekday !== '*' && f.day === '*') {
    const days = f.weekday.split(',').map(d => WEEKDAYS[parseInt(d)] || d).join('、')
    return `每${days} ${f.hour.padStart(2, '0')}:${f.minute.padStart(2, '0')}`
  }
  // 每月
  if (f.day !== '*' && f.weekday === '*') {
    return `每月 ${f.day} 号 ${f.hour.padStart(2, '0')}:${f.minute.padStart(2, '0')}`
  }

  return expr
}

export function CronEditor({ value, onChange }) {
  const currentExpr = value || '0 8 * * *'
  const fields = useMemo(() => parseCron(currentExpr), [currentExpr])
  const desc = useMemo(() => describeCron(currentExpr), [currentExpr])
  const [showCustom, setShowCustom] = useState(false)

  // 检测当前是否匹配某个预设
  const matchedPreset = PRESETS.find(p => p.value === currentExpr)
  const isPreset = !!matchedPreset && !showCustom
  const isCustom = !isPreset || showCustom

  const handlePresetClick = (preset) => {
    if (preset.label === '自定义') {
      setShowCustom(true)
    } else {
      setShowCustom(false)
      onChange(preset.value)
    }
  }

  const handleFieldChange = (fieldKey, fieldValue) => {
    const newFields = { ...fields, [fieldKey]: fieldValue }
    onChange(buildCron(newFields))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {/* 预设模式 */}
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {PRESETS.map(p => (
          <button
            key={p.label}
            className="btn btn-ghost"
            style={{
              padding: '4px 8px',
              fontSize: 12,
              background: (isPreset && matchedPreset?.label === p.label) || (showCustom && p.label === '自定义')
                ? 'rgba(99,102,241,0.15)'
                : 'transparent',
              border: '1px solid var(--border-primary)',
              borderRadius: 6,
            }}
            onClick={() => handlePresetClick(p)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* 自定义编辑 */}
      {isCustom && (
        <div style={{
          padding: 8,
          background: 'var(--bg-tertiary)',
          borderRadius: 6,
        }}>
          <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
            {FIELDS.slice(0, 3).map(f => (
              <div key={f.key} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
                <label style={{ fontSize: 11, color: 'var(--text-secondary)', textAlign: 'center' }}>
                  {f.label}
                </label>
                <input
                  className="form-input"
                  style={{ textAlign: 'center', padding: '4px', fontSize: 13, width: '100%', boxSizing: 'border-box' }}
                  value={fields[f.key]}
                  onChange={(e) => handleFieldChange(f.key, e.target.value)}
                  placeholder={f.default}
                />
                <span style={{ fontSize: 10, color: 'var(--text-muted)', textAlign: 'center' }}>
                  {f.help}
                </span>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {FIELDS.slice(3).map(f => (
              <div key={f.key} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
                <label style={{ fontSize: 11, color: 'var(--text-secondary)', textAlign: 'center' }}>
                  {f.label}
                </label>
                <input
                  className="form-input"
                  style={{ textAlign: 'center', padding: '4px', fontSize: 13, width: '100%', boxSizing: 'border-box' }}
                  value={fields[f.key]}
                  onChange={(e) => handleFieldChange(f.key, e.target.value)}
                  placeholder={f.default}
                />
                <span style={{ fontSize: 10, color: 'var(--text-muted)', textAlign: 'center' }}>
                  {f.help}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 人类可读描述 */}
      <div style={{
        padding: '6px 10px',
        background: 'rgba(99,102,241,0.08)',
        borderRadius: 6,
        fontSize: 13,
        color: 'var(--text-primary)',
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}>
        <span style={{ fontSize: 14 }}>🕐</span>
        <span>{desc}</span>
      </div>

      {/* 原始表达式 */}
      <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
        cron: {currentExpr}
      </div>
    </div>
  )
}
