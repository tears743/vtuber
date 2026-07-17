import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ReactFlowProvider } from '@xyflow/react'
import { WorkflowList } from './pages/WorkflowList'
import { WorkflowEditor } from './pages/WorkflowEditor'
import { SettingsPage } from './pages/SettingsPage'
import { TimelinePage } from './pages/TimelinePage'
import { CustomNodesPage } from './pages/CustomNodesPage'
import { CustomToolsPage } from './pages/CustomToolsPage'
import { CustomWorkflowsPage } from './pages/CustomWorkflowsPage'
import { Sidebar } from './components/Sidebar'
import './index.css'

function App() {
  return (
    <BrowserRouter>
      <ReactFlowProvider>
        <div className="app-layout">
          <Sidebar />
          <div className="app-main">
            <Routes>
              <Route path="/" element={<WorkflowList />} />
              <Route path="/workflow/:id" element={<WorkflowEditor />} />
              <Route path="/timeline" element={<TimelinePage />} />
              <Route path="/custom-nodes" element={<CustomNodesPage />} />
              <Route path="/custom-tools" element={<CustomToolsPage />} />
          <Route path="/custom-workflows" element={<CustomWorkflowsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </div>
        </div>
      </ReactFlowProvider>
    </BrowserRouter>
  )
}

export default App

