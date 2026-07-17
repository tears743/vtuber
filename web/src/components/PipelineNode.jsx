import { Handle, Position } from '@xyflow/react'

const CATEGORY_CSS = {
  数据采集: 'cat-collect',
  内容处理: 'cat-process',
  音视频: 'cat-audio',
  输出: 'cat-output',
}

const TYPE_ICONS = {
  collect: '采',
  download: '下',
  recognize: '识',
  transcribe: '转',
  director: '编',
  tts: '音',
  align: '齐',
  overlay: '字',
  visual: '景',
  live2d: '人',
  compose: '合',
}

const HEADER_HEIGHT = 42
const ROW_HEIGHT = 24

export function PipelineNode({ data, selected }) {
  const { label, type, category, status, progress, progressMessage } = data
  const icon = TYPE_ICONS[type] || '节'
  const catCss = CATEGORY_CSS[category] || 'cat-collect'
  const inputs = normalizeInputs(type, data.inputs || [])
  const outputs = data.outputs || []
  const rowCount = Math.max(inputs.length, outputs.length, 1)
  const showStatus = status === 'running' || status === 'completed' || status === 'failed' || status === 'cached'
  const nodeHeight = HEADER_HEIGHT + rowCount * ROW_HEIGHT + (showStatus ? 8 : 0) + 8

  let statusClass = ''
  if (status === 'running') statusClass = 'running'
  else if (status === 'completed' || status === 'cached') statusClass = 'completed'
  else if (status === 'failed') statusClass = 'failed'

  return (
    <div className={`custom-node ${statusClass} ${selected ? 'selected' : ''}`} style={{ minHeight: nodeHeight }}>
      {inputs.map((port, index) => (
        <Handle
          key={port.name}
          id={port.name}
          type="target"
          position={Position.Left}
          className="node-port-handle node-port-handle-input"
          style={{ top: `${HEADER_HEIGHT + index * ROW_HEIGHT + ROW_HEIGHT / 2}px` }}
          title={`${port.name}: ${port.type || '*'}`}
        />
      ))}

      <div className="node-header">
        <div className={`node-icon ${catCss}`}>{icon}</div>
        <span className="node-label">{label || type}</span>
      </div>

      <div className="node-ports" style={{ gridTemplateRows: `repeat(${rowCount}, ${ROW_HEIGHT}px)` }}>
        {Array.from({ length: rowCount }).map((_, index) => {
          const input = inputs[index]
          const output = outputs[index]
          return (
            <div className="node-port-row" key={index}>
              <PortLabel port={input} side="input" />
              <PortLabel port={output} side="output" />
            </div>
          )
        })}
      </div>

      {showStatus && (
        <div className="node-status">
          {status === 'running' && progressMessage && (
            <div className="node-status-message" title={progressMessage}>{progressMessage}</div>
          )}
          <div className="node-status-bar">
            <div
              className={`node-status-fill ${status === 'running' ? 'running' : ''} ${status === 'completed' || status === 'cached' ? 'completed' : ''} ${status === 'failed' ? 'failed' : ''}`}
              style={{ width: `${Math.max(status === 'running' ? 3 : 0, (progress || 0) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {outputs.map((port, index) => (
        <Handle
          key={port.name}
          id={port.name}
          type="source"
          position={Position.Right}
          className="node-port-handle node-port-handle-output"
          style={{ top: `${HEADER_HEIGHT + index * ROW_HEIGHT + ROW_HEIGHT / 2}px` }}
          title={`${port.name}: ${port.type || '*'}`}
        />
      ))}
    </div>
  )
}

function PortLabel({ port, side }) {
  if (!port) return <div className={`node-port-label node-port-label-${side} empty`} />
  const type = port.type || '*'
  const title = port.label || port.name
  const direction = side === 'input' ? '输入' : '输出'
  const schema = port.format_schema

  return (
    <div className={`node-port-label node-port-label-${side} has-port-tooltip`}>
      {side === 'output' && <span className="node-port-type">{type}</span>}
      <span className="node-port-name">{port.name}</span>
      {side === 'input' && <span className="node-port-type">{type}</span>}
      <div className={`node-port-tooltip node-port-tooltip-${side}`} role="tooltip">
        <div className="node-port-tooltip-title">{title}</div>
        <div className="node-port-tooltip-row">
          <span>方向</span>
          <strong>{direction}</strong>
        </div>
        <div className="node-port-tooltip-row">
          <span>字段</span>
          <strong>{port.name}</strong>
        </div>
        <div className="node-port-tooltip-row">
          <span>数据格式</span>
          <strong>{type}</strong>
        </div>
        <PortFormatDetails schema={schema} fallbackText={port.format_text} />
        {side === 'input' && (
          <div className="node-port-tooltip-row">
            <span>连接</span>
            <strong>{port.multi ? '可接多个上游' : '单个上游'}</strong>
          </div>
        )}
        {side === 'input' && (
          <div className="node-port-tooltip-row">
            <span>要求</span>
            <strong>{port.required ? '必填' : '可选'}</strong>
          </div>
        )}
        {port.description && <div className="node-port-tooltip-desc">{port.description}</div>}
        {port.default !== undefined && port.default !== null && port.default !== '' && (
          <div className="node-port-tooltip-desc">默认值: {formatPortValue(port.default)}</div>
        )}
      </div>
    </div>
  )
}

function PortFormatDetails({ schema, fallbackText }) {
  const fields = schema?.fields || []
  const description = schema?.description
  const hasFallback = fallbackText && fallbackText !== schema?.type

  if (!description && fields.length === 0 && !hasFallback) return null

  return (
    <div className="node-port-format">
      {description && <div className="node-port-format-desc">{description}</div>}
      {fields.length > 0 && (
        <div className="node-port-format-fields">
          {fields.map(field => (
            <div className="node-port-format-field" key={field.name}>
              <div className="node-port-format-field-main">
                <span className="node-port-format-field-name">{field.name}</span>
                <span className="node-port-format-field-type">{field.type || 'Any'}</span>
              </div>
              <div className="node-port-format-field-meta">
                {field.required ? '必填' : '可选'}
                {field.description ? ` · ${field.description}` : ''}
              </div>
            </div>
          ))}
        </div>
      )}
      {fields.length === 0 && hasFallback && <pre className="node-port-format-text">{fallbackText}</pre>}
    </div>
  )
}

function formatPortValue(value) {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  try {
    const json = JSON.stringify(value)
    return json.length > 80 ? `${json.slice(0, 77)}...` : json
  } catch {
    return String(value)
  }
}

function normalizeInputs(type, inputs) {
  if (type === 'collect' && inputs.length === 0) {
    return [{ name: 'trigger', label: '触发', type: 'Trigger', required: false }]
  }
  return inputs
}

export const nodeTypes = {
  pipeline: PipelineNode,
}
