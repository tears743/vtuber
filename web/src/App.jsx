import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { WorkflowList } from './pages/WorkflowList'
import { WorkflowEditor } from './pages/WorkflowEditor'
import { SettingsPage } from './pages/SettingsPage'
import { TimelinePage } from './pages/TimelinePage'
import { Sidebar } from './components/Sidebar'
import './index.css'

function App() {
  return (
    <BrowserRouter>
      <div className="app-layout">
        <Sidebar />
        <div className="app-main">
          <Routes>
            <Route path="/" element={<WorkflowList />} />
            <Route path="/workflow/:id" element={<WorkflowEditor />} />
            <Route path="/timeline" element={<TimelinePage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  )
}

export default App

