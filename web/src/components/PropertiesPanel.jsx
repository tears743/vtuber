/**
 * 右侧属性面板 — 编辑选中节点的配置
 */
import { useEffect, useState } from 'react'
import { PromptEditor } from './PromptEditor'
import { CronEditor } from './CronEditor'
import { api } from '../api'

export function PropertiesPanel({ selectedNode, nodeDefinitions, onConfigChange, onRunNode, onRunFromNode, onClearNodeCache }) {
  const [editingPrompt, setEditingPrompt] = useState(null) // {key, field}
  const [models, setModels] = useState([])

  useEffect(() => {
    api.listModels()
      .then(data => setModels(Array.isArray(data) ? data : []))
      .catch(() => setModels([]))
  }, [])

  if (!selectedNode) {
    return (
      <div className="properties-panel">
        <div className="panel-header">属性</div>
        <div className="panel-body">
          <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            点击画布中的节点查看属性
          </p>
        </div>
      </div>
    )
  }

  const nodeDef = nodeDefinitions?.find(d => d.type === selectedNode.data.type)
  const schema = nodeDef?.config_schema || {}
  const config = selectedNode.data.config || {}

  const handleChange = (key, value) => {
    const newConfig = { ...config, [key]: value }
    onConfigChange(selectedNode.id, newConfig)
  }

  return (
    <div className="properties-panel">
      <div className="panel-header">
        {selectedNode.data.label}
        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: 8 }}>
          {selectedNode.data.type}
        </span>
      </div>
      <div className="panel-body">
        <div className="form-group">
          <label className="form-label">节点 ID</label>
          <input className="form-input" value={selectedNode.id} disabled />
        </div>

        {/* 手动触发按钮 */}
        <button
          className="btn btn-primary"
          style={{ width: '100%', marginBottom: 8, padding: '6px 12px', fontSize: 13 }}
          onClick={() => onRunNode?.(selectedNode.id)}
        >
          ▶ 手动触发
        </button>

        <button
          className="btn btn-success"
          style={{ width: '100%', marginBottom: 8, padding: '6px 12px', fontSize: 13 }}
          onClick={() => onRunFromNode?.(selectedNode.id)}
        >
          从此节点恢复运行
        </button>

        <button
          className="btn btn-danger"
          style={{ width: '100%', marginBottom: 8, padding: '6px 12px', fontSize: 13 }}
          onClick={() => onClearNodeCache?.(selectedNode.id)}
        >
          清除节点缓存
        </button>

        <div className="form-group">
          <label className="form-label">Reads</label>
          <input className="form-input" value={nodeDef?.reads?.join(', ') || '—'} disabled />
        </div>
        <div className="form-group">
          <label className="form-label">Writes</label>
          <input className="form-input" value={nodeDef?.writes?.join(', ') || '—'} disabled />
        </div>

        <hr style={{ borderColor: 'var(--border-primary)', margin: '8px 0' }} />

        {Object.entries(schema).map(([key, field]) => (
          <div className="form-group" key={key}>
            <label className="form-label">
              {field.label || key}
            </label>
            {field.description && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, lineHeight: 1.4 }}>
                {field.description}
              </div>
            )}
            {renderField(key, field, config[key], handleChange, setEditingPrompt, models)}
          </div>
        ))}
      </div>

      {/* 全屏 Prompt 编辑器弹窗 */}
      {editingPrompt && (
        <PromptEditor
          value={config[editingPrompt.key] ?? editingPrompt.field.default ?? ''}
          label={editingPrompt.field.label || editingPrompt.key}
          variables={editingPrompt.field.variables || []}
          onChange={(val) => handleChange(editingPrompt.key, val)}
          onClose={() => setEditingPrompt(null)}
        />
      )}
    </div>
  )
}

function renderField(key, field, value, onChange, setEditingPrompt, models = []) {
  const type = key === 'model' ? 'model' : field.type

  if (type === 'cron') {
    return (
      <CronEditor
        value={value ?? field.default ?? '0 8 * * *'}
        onChange={(val) => onChange(key, val)}
      />
    )
  }

  if (type === 'date') {
    return (
      <input
        className="form-input"
        type="date"
        value={value ?? field.default ?? ''}
        onChange={(e) => onChange(key, e.target.value)}
      />
    )
  }

  if (type === 'text') {
    // 长文本指令 → 用触发按钮打开全屏编辑器
    const currentVal = value ?? field.default ?? ''
    const preview = currentVal
      ? currentVal.slice(0, 40) + (currentVal.length > 40 ? '...' : '')
      : '(空，点击编辑)'
    const lineCount = currentVal ? currentVal.split('\n').length : 0

    return (
      <div
        className="prompt-trigger"
        onClick={() => setEditingPrompt({ key, field })}
      >
        <span className="prompt-trigger-text">{preview}</span>
        <span className="prompt-trigger-badge">
          {lineCount > 0 ? `${lineCount} 行` : '编辑'}
        </span>
      </div>
    )
  }

  if (type === 'enum') {
    return (
      <select
        className="form-input form-select"
        value={value ?? field.default ?? ''}
        onChange={(e) => onChange(key, e.target.value)}
      >
        {(field.options || []).map(opt => (
          <option
            key={typeof opt === 'object' ? opt.value : opt}
            value={typeof opt === 'object' ? opt.value : opt}
          >
            {typeof opt === 'object' ? (opt.label || opt.value) : opt}
          </option>
        ))}
      </select>
    )
  }

  if (type === 'model') {
    const currentValue = value ?? field.default ?? ''
    const hasCurrentValue = currentValue && !models.some(model => model.name === currentValue)
    return (
      <select
        className="form-input form-select"
        value={currentValue}
        onChange={(e) => onChange(key, e.target.value)}
      >
        <option value="">请选择模型</option>
        {hasCurrentValue && (
          <option value={currentValue}>{currentValue}（未在全局模型中找到）</option>
        )}
        {models.map(model => (
          <option key={model.name} value={model.name}>
            {model.name}{model.capabilities?.length ? ` (${model.capabilities.join(', ')})` : ''}
          </option>
        ))}
      </select>
    )
    return (
      <input
        className="form-input"
        value={value ?? field.default ?? ''}
        onChange={(e) => onChange(key, e.target.value)}
        placeholder={field.description || '模型名称'}
      />
    )
  }

  if (type === 'int' || type === 'float') {
    return (
      <input
        className="form-input"
        type="number"
        value={value ?? field.default ?? ''}
        min={field.min}
        max={field.max}
        step={field.step || (type === 'float' ? 0.1 : 1)}
        onChange={(e) => onChange(key, type === 'int' ? parseInt(e.target.value) : parseFloat(e.target.value))}
      />
    )
  }

  if (type === 'bool') {
    return (
      <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          type="checkbox"
          checked={value ?? field.default ?? false}
          onChange={(e) => onChange(key, e.target.checked)}
        />
        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>启用</span>
      </label>
    )
  }

  if (type === 'list') {
    return (
      <input
        className="form-input"
        value={Array.isArray(value) ? value.join(', ') : (value ?? (field.default || []).join(', '))}
        onChange={(e) => onChange(key, e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
        placeholder="逗号分隔"
      />
    )
  }

  // default: string
  return (
    <input
      className="form-input"
      value={value ?? field.default ?? ''}
      onChange={(e) => onChange(key, e.target.value)}
    />
  )
}
