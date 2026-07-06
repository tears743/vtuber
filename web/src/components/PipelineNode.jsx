/**
 * 自定义节点组件 — React Flow 渲染
 */
import { Handle, Position } from '@xyflow/react'

const CATEGORY_ICONS = {
  '数据采集': '📥',
  '内容处理': '🧠',
  '音视频': '🎬',
  '输出': '📤',
}

const CATEGORY_CSS = {
  '数据采集': 'cat-collect',
  '内容处理': 'cat-process',
  '音视频': 'cat-audio',
  '输出': 'cat-output',
}

const TYPE_ICONS = {
  collect: '🕷️',
  download: '⬇️',
  recognize: '👁️',
  transcribe: '🎙️',
  director: '🎬',
  tts: '🗣️',
  align: '⏱️',
  overlay: '🎴',
  visual: '🖼️',
  live2d: '🧑🎤',
  compose: '🎞️',
}

export function PipelineNode({ data, selected }) {
  const { label, type, category, status, progress } = data
  const icon = TYPE_ICONS[type] || '⚙️'
  const catCss = CATEGORY_CSS[category] || 'cat-collect'

  let statusClass = ''
  if (status === 'running') statusClass = 'running'
  else if (status === 'completed') statusClass = 'completed'
  else if (status === 'failed') statusClass = 'failed'

  return (
    <div className={`custom-node ${statusClass} ${selected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} />

      <div className="node-header">
        <div className={`node-icon ${catCss}`}>{icon}</div>
        <span className="node-label">{label}</span>
      </div>

      {(status === 'running' || status === 'completed' || status === 'failed') && (
        <div className="node-status-bar">
          <div
            className={`node-status-fill ${status === 'completed' ? 'completed' : ''} ${status === 'failed' ? 'failed' : ''}`}
            style={{ width: `${(progress || 0) * 100}%` }}
          />
        </div>
      )}

      <Handle type="source" position={Position.Right} />
    </div>
  )
}

// React Flow 需要的 nodeTypes 映射
export const nodeTypes = {
  pipeline: PipelineNode,
}
