import { useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { AdminSkillsPage } from '../components/AdminSkillsPage'
import { ChatManageShell } from '../components/ChatManageShell'
import { useAdminAssetBundle } from '../hooks/useAdminAssetBundle'
import type { SemanticsSubTab } from '../components/AdminSemanticsHub'

export default function ChatManageSkills() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const user = JSON.parse(localStorage.getItem('user') || '{}')
  const isAdmin = user.role === 'admin' || user.role === 'manager'
  const [skillCode, setSkillCode] = useState<string | null>(searchParams.get('skill'))
  const [uploadOpen, setUploadOpen] = useState(false)


  const {
    enabledSkills,
    workflowNodes,
    llmConfig,
    loading,
    error,
    reload,
  } = useAdminAssetBundle()

  if (!isAdmin) return <Navigate to="/chat" replace />

  const onNavigate = (tab: string) => {
    if (tab === 'llm') {
      navigate('/chat/manage/assets/llm')
      return
    }
    if (tab === 'rules') {
      navigate('/chat/manage/assets/rules')
      return
    }
    const sem = (['datasources', 'entities', 'mapping', 'graph'] as const).includes(tab as SemanticsSubTab)
      ? tab
      : 'mapping'
    navigate(`/chat/manage/assets/semantics?sem=${sem}`)
  }

  return (
    <ChatManageShell
      title="技能中心"
      loading={loading}
      error={error}
      onRetry={reload}
      fullWidth
      minimal
    >
      <AdminSkillsPage
        enabledSkills={enabledSkills}
        workflowNodes={workflowNodes}
        llmConfig={llmConfig}
        initialSkillCode={skillCode}
        onInitialSkillHandled={() => setSkillCode(null)}
        onNavigate={onNavigate}
        allowUpload
        compact
        uploadOpen={uploadOpen}
        onUploadOpenChange={setUploadOpen}
      />
    </ChatManageShell>
  )
}
