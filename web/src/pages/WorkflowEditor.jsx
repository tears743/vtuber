/**
 * 工作流编辑器页面
 * React Flow 画布 + 左侧节点库 + 右侧属性面板 + 顶部工具栏
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  useReactFlow,
  BackgroundVariant,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { api, createRunSocket } from '../api'
import { nodeTypes } from '../components/PipelineNode'
import { PropertiesPanel } from '../components/PropertiesPanel'
import { RunDialog } from '../components/RunDialog'
import { LogPanel } from '../components/LogPanel'
import { TimelinePanel } from '../components/TimelinePanel'

export function WorkflowEditor() {
  const { id } = useParams()
  const { screenToFlowPosition } = useReactFlow()
  const [workflow, setWorkflow] = useState(null)
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [selectedNode, setSelectedNode] = useState(null)
  const [nodeDefinitions, setNodeDefinitions] = useState([])
  const [nodeCategories, setNodeCategories] = useState({})
  const [runState, setRunState] = useState(null)
  const [showRunDialog, setShowRunDialog] = useState(false)
  const [logs, setLogs] = useState([])
  const [logsExpanded, setLogsExpanded] = useState(false)
  const [timelineExpanded, setTimelineExpanded] = useState(false)
  const [runDate, setRunDate] = useState(null)
  const wsRef = useRef(null)

  // 加载工作流和节点定义
  useEffect(() => {
    Promise.all([
      api.getWorkflow(id),
      api.listNodes(),
      api.listNodeCategories(),
    ]).then(([wf, nodesResp, cats]) => {
      // listNodes() 返回 {nodes: [...], node_packs: [...], global_config: {...}}
      const defs = nodesResp.nodes || nodesResp || []
      setWorkflow(wf)
      setNodeDefinitions(defs)
      setNodeCategories(cats)

      // 转换为 React Flow 格式
      const rfNodes = (wf.nodes || []).map(n => {
        const def = defs.find(d => d.type === n.type) || {}
        return {
          id: n.id,
          type: 'pipeline',
          position: n.position || { x: 0, y: 0 },
          data: {
            label: def.label || n.type,
            type: n.type,
            category: def.category || '',
            config: n.config || {},
            status: null,
            progress: 0,
          },
        }
      })
      const rfEdges = (wf.edges || []).map((e, i) => ({
        id: `edge-${i}`,
        source: e.source,
        target: e.target,
        animated: false,
        style: { stroke: 'rgba(99,102,241,0.4)', strokeWidth: 2 },
      }))
      setNodes(rfNodes)
      setEdges(rfEdges)
    }).catch(console.error)
  }, [id])

  // WebSocket 连接
  useEffect(() => {
    wsRef.current = createRunSocket((msg) => {
      setRunState(msg)
      // 更新节点状态
      if (msg.type === 'node_start') {
        setNodes(nds => nds.map(n =>
          n.id === msg.data.node_id
            ? { ...n, data: { ...n.data, status: 'running', progress: 0 } }
            : n
        ))
      } else if (msg.type === 'node_progress') {
        setNodes(nds => nds.map(n =>
          n.id === msg.data.node_id
            ? { ...n, data: { ...n.data, progress: msg.data.progress } }
            : n
        ))
      } else if (msg.type === 'node_complete') {
        // 当 align 或 director 节点完成时，自动展开时间轴
        const completedType = msg.data.node_type || ''
        if (completedType === 'align' || completedType === 'director') {
          setTimelineExpanded(true)
        }
        setNodes(nds => nds.map(n =>
          n.id === msg.data.node_id
            ? { ...n, data: { ...n.data, status: 'completed', progress: 1 } }
            : n
        ))
      } else if (msg.type === 'node_error') {
        setNodes(nds => nds.map(n =>
          n.id === msg.data.node_id
            ? { ...n, data: { ...n.data, status: 'failed' } }
            : n
        ))
      } else if (msg.type === 'node_cached') {
        setNodes(nds => nds.map(n =>
          n.id === msg.data.node_id
            ? { ...n, data: { ...n.data, status: 'cached', progress: 1 } }
            : n
        ))
      } else if (msg.type === 'log') {
        setLogs(prev => [...prev.slice(-500), msg.data])  // 保留最近 500 条
        if (msg.data.level === 'ERROR') setLogsExpanded(true)
      } else if (msg.type === 'run_start') {
        setLogs([])  // 新运行清空日志
        setLogsExpanded(true)
        setRunState({ status: 'running' })
      } else if (msg.type === 'run_end' || msg.type === 'run_stopped') {
        setRunState({ status: 'idle' })
      }
    })
    return () => wsRef.current?.close()
  }, [])

  const onConnect = useCallback((params) => {
    setEdges(eds => addEdge({ ...params, style: { stroke: 'rgba(99,102,241,0.4)', strokeWidth: 2 } }, eds))
  }, [setEdges])

  const onNodeClick = useCallback((_, node) => {
    setSelectedNode(node)
  }, [])

  const onPaneClick = useCallback(() => {
    setSelectedNode(null)
  }, [])

  const handleConfigChange = useCallback((nodeId, newConfig) => {
    setNodes(nds => nds.map(n =>
      n.id === nodeId ? { ...n, data: { ...n.data, config: newConfig } } : n
    ))
  }, [setNodes])

  // 保存
  const handleSave = async () => {
    const wfNodes = nodes.map(n => ({
      id: n.id,
      type: n.data.type,
      position: n.position,
      config: n.data.config || {},
    }))
    const wfEdges = edges.map(e => ({ source: e.source, target: e.target }))
    await api.updateWorkflow(id, { nodes: wfNodes, edges: wfEdges })
  }

  // 运行（弹出参数选择）
  const handleRun = () => {
    setShowRunDialog(true)
  }

  // 确认运行
  const handleRunConfirm = async ({ date, forceNoCache }) => {
    setShowRunDialog(false)
    setRunState({ status: 'running' })  // 立即设置状态
    setRunDate(date)  // 记录运行日期供 timeline 使用
    // 重置节点状态
    setNodes(nds => nds.map(n => ({ ...n, data: { ...n.data, status: null, progress: 0 } })))
    await handleSave()
    await api.startRun({ workflow_id: id, date, force_no_cache: forceNoCache })
  }

  // 停止
  const handleStop = async () => {
    await api.stopRun()
  }

  // 拖放新节点
  const onDragOver = useCallback((e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback((e) => {
    e.preventDefault()
    const type = e.dataTransfer.getData('application/node-type')
    if (!type) return

    const def = nodeDefinitions.find(d => d.type === type)
    if (!def) return

    // 用 React Flow 的 screenToFlowPosition 将屏幕坐标转为画布坐标
    const position = screenToFlowPosition({ x: e.clientX, y: e.clientY })

    const newId = `${type}_${Date.now().toString(36)}`
    const newNode = {
      id: newId,
      type: 'pipeline',
      position,
      data: {
        label: def.label,
        type: def.type,
        category: def.category,
        config: {},
        status: null,
        progress: 0,
      },
    }
    setNodes(nds => [...nds, newNode])
  }, [nodeDefinitions, setNodes, screenToFlowPosition])

  const minimapNodeColor = (node) => {
    const cat = node.data?.category
    if (cat === '数据采集') return '#6366f1'
    if (cat === '内容处理') return '#a78bfa'
    if (cat === '音视频') return '#22d3ee'
    if (cat === '输出') return '#34d399'
    return '#6b7280'
  }

  if (!workflow) return <div className="page-workflows"><p>加载中...</p></div>

  return (
    <div style={{ display: 'flex', height: '100vh', flexDirection: 'column' }}>
      {/* Toolbar */}
      <div className="toolbar">
        <div className="toolbar-left">
          <span className="toolbar-title">{workflow.name}</span>
          {runState?.status === 'running' && (
            <span className="toolbar-status running">● 运行中</span>
          )}
        </div>
        <div className="toolbar-right">
          <button className="btn btn-ghost" onClick={handleSave} disabled={runState?.status === 'running'}>💾 保存</button>
          <button className="btn btn-primary" onClick={handleRun} disabled={runState?.status === 'running'}>
            {runState?.status === 'running' ? '⚡ 执行中...' : '▶️ 运行'}
          </button>
          <button className="btn btn-danger" onClick={handleStop} disabled={runState?.status !== 'running'}>⏹ 停止</button>
        </div>
      </div>

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', minHeight: 0 }}>
        {/* Left Node Library */}
        <div style={{ width: 200, background: 'var(--bg-secondary)', borderRight: '1px solid var(--border-primary)', overflow: 'auto' }}>
          {Object.entries(nodeCategories).map(([cat, defs]) => (
            <div key={cat} className="node-library">
              <div className="node-library-title">{cat}</div>
              {defs.map(d => (
                <div
                  key={d.type}
                  className="node-library-item"
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/node-type', d.type)
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                >
                  <span>{d.label}</span>
                </div>
              ))}
            </div>
          ))}
        </div>

        {/* Canvas */}
        <div style={{ flex: 1 }} onDragOver={onDragOver} onDrop={onDrop}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            nodeTypes={nodeTypes}
            deleteKeyCode={['Backspace', 'Delete']}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="rgba(255,255,255,0.05)" />
            <Controls position="bottom-left" />
            <MiniMap
              nodeColor={minimapNodeColor}
              maskColor="rgba(0,0,0,0.7)"
              style={{ background: 'var(--bg-tertiary)' }}
            />
          </ReactFlow>
        </div>

        {/* Right Panel */}
        <PropertiesPanel
          selectedNode={selectedNode}
          nodeDefinitions={nodeDefinitions}
          onConfigChange={handleConfigChange}
        />
      </div>

      {/* Timeline Panel */}
      <TimelinePanel
        isExpanded={timelineExpanded}
        onToggle={() => setTimelineExpanded(!timelineExpanded)}
        runDate={runDate}
      />

      {/* Log Panel */}
      <LogPanel
        logs={logs}
        isExpanded={logsExpanded}
        onToggle={() => setLogsExpanded(!logsExpanded)}
      />

      {/* Run Dialog */}
      {showRunDialog && (
        <RunDialog
          onConfirm={handleRunConfirm}
          onCancel={() => setShowRunDialog(false)}
        />
      )}
    </div>
  )
}
