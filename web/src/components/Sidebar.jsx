import { NavLink } from 'react-router-dom'

export function Sidebar() {
  return (
    <aside className="app-sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <div className="logo-icon">⚡</div>
          VideoFactory
        </div>
      </div>
      <nav className="sidebar-nav">
        <NavLink to="/" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`} end>
          📋 工作流
        </NavLink>
        <NavLink to="/timeline" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          🎬 时间轴
        </NavLink>
        <NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          ⚙️ 设置
        </NavLink>
      </nav>
    </aside>
  )
}
