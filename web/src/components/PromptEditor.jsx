/**
 * PromptEditor — 全屏弹窗 Prompt 编辑器
 * 
 * 特性:
 * - 全屏 overlay 弹窗
 * - {{变量}} 高亮显示
 * - 变量插入选择器
 * - 行号显示
 * - Esc 关闭
 */
import { useState, useRef, useEffect, useCallback } from 'react'

export function PromptEditor({ value, onChange, label, variables = [], onClose }) {
  const [text, setText] = useState(value || '')
  const textareaRef = useRef(null)
  const [showVarPicker, setShowVarPicker] = useState(false)

  useEffect(() => {
    // 打开时聚焦
    textareaRef.current?.focus()
    // Esc 关闭
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose])

  const handleSave = () => {
    onChange(text)
    onClose()
  }

  const insertVariable = (varName) => {
    const el = textareaRef.current
    if (!el) return
    const start = el.selectionStart
    const end = el.selectionEnd
    const before = text.slice(0, start)
    const after = text.slice(end)
    const insert = `{{${varName}}}`
    const newText = before + insert + after
    setText(newText)
    setShowVarPicker(false)
    // 恢复光标
    requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = start + insert.length
      el.focus()
    })
  }

  const lineCount = text.split('\n').length

  return (
    <div className="prompt-editor-overlay" onClick={onClose}>
      <div className="prompt-editor-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="prompt-editor-header">
          <div className="prompt-editor-title">
            <span className="prompt-editor-icon">📝</span>
            {label || '编辑指令'}
          </div>
          <div className="prompt-editor-actions">
            {variables.length > 0 && (
              <div className="prompt-var-picker-wrap">
                <button
                  className="btn btn-ghost"
                  onClick={() => setShowVarPicker(!showVarPicker)}
                >
                  {'{{x}}'} 插入变量
                </button>
                {showVarPicker && (
                  <div className="prompt-var-dropdown">
                    {variables.map(v => (
                      <div
                        key={v.name}
                        className="prompt-var-item"
                        onClick={() => insertVariable(v.name)}
                      >
                        <span className="prompt-var-name">{`{{${v.name}}}`}</span>
                        <span className="prompt-var-desc">{v.description}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            <button className="btn btn-ghost" onClick={onClose}>取消</button>
            <button className="btn btn-primary" onClick={handleSave}>保存</button>
          </div>
        </div>

        {/* Editor body */}
        <div className="prompt-editor-body">
          <div className="prompt-editor-lines">
            {Array.from({ length: lineCount }, (_, i) => (
              <div key={i} className="prompt-line-number">{i + 1}</div>
            ))}
          </div>
          <textarea
            ref={textareaRef}
            className="prompt-editor-textarea"
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
          />
        </div>

        {/* Footer */}
        <div className="prompt-editor-footer">
          <span>{lineCount} 行 · {text.length} 字符</span>
          <span>Esc 关闭 · Ctrl+S 保存</span>
        </div>
      </div>
    </div>
  )
}
