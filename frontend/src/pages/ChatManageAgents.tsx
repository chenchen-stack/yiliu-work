import { Navigate } from 'react-router-dom'
import AdminAgentsPage from '../components/AdminAgentsPage'
import { ChatManageShell } from '../components/ChatManageShell'

export default function ChatManageAgents() {
  const user = JSON.parse(localStorage.getItem('user') || '{}')
  const isAdmin = user.role === 'admin' || user.role === 'manager'
  if (!isAdmin) return <Navigate to="/chat" replace />

  return (
    <ChatManageShell title="智能体中心" fullWidth minimal>
      <AdminAgentsPage frontOnly />
    </ChatManageShell>
  )
}
