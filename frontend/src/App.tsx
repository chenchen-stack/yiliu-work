import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import AppLayout from './layouts/AppLayout'
import Login from './pages/Login'
import ChatCenter from './pages/ChatCenter'
import AgentCenter from './pages/AgentCenter'
import ChatManageAgents from './pages/ChatManageAgents'
import ChatManageSkills from './pages/ChatManageSkills'
import ChatManageAsset from './pages/ChatManageAsset'
import AdminCenter from './pages/AdminCenter'
import Dashboard from './pages/Dashboard'
import TaskList from './pages/TaskList'
import TaskCreate from './pages/TaskCreate'
import TaskDetail from './pages/TaskDetail'

function TaskRedirect() {
  const { id } = useParams()
  return <Navigate to={`/workbench/reconciliation/tasks/${id}`} replace />
}

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token')
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '') || '/'}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<PrivateRoute><AppLayout /></PrivateRoute>}>
          <Route index element={<Navigate to="/workbench/reconciliation" replace />} />
          <Route path="chat" element={<ChatCenter />} />
          <Route path="chat/manage/agents" element={<ChatManageAgents />} />
          <Route path="chat/manage/skills" element={<ChatManageSkills />} />
          <Route path="chat/manage/assets/semantics" element={<ChatManageAsset assetKey="semantics" />} />
          <Route path="chat/manage/assets/rules" element={<ChatManageAsset assetKey="rules" />} />
          <Route path="chat/manage/assets/llm" element={<ChatManageAsset assetKey="llm" />} />
          <Route path="agents" element={<AgentCenter />} />
          <Route path="scenarios" element={<Navigate to="/workbench/reconciliation" replace />} />
          <Route path="admin" element={<AdminCenter />} />
          <Route path="workbench/reconciliation" element={<Dashboard />} />
          <Route path="workbench/reconciliation/tasks" element={<TaskList />} />
          <Route path="workbench/reconciliation/tasks/new" element={<TaskCreate />} />
          <Route path="workbench/reconciliation/tasks/:id" element={<TaskDetail />} />
          {/* 兼容旧路由 */}
          <Route path="tasks" element={<Navigate to="/workbench/reconciliation/tasks" replace />} />
          <Route path="tasks/new" element={<Navigate to="/workbench/reconciliation/tasks/new" replace />} />
          <Route path="tasks/:id" element={<TaskRedirect />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
