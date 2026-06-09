import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Dropdown, Spin } from 'antd'
import {
  DownOutlined, PlusOutlined, SettingOutlined, LogoutOutlined, HistoryOutlined,
  RobotOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { usePublishedCenter } from '../context/PublishedCenterContext'
import { WORKBENCH_NAV, type WorkbenchNavItem } from '../config/workbenchNav'
import { ConversationListItem, getChatConversations } from '../api/client'

const ROLE_LABELS: Record<string, string> = {
  admin: '平台管理员',
  manager: '平台管理员',
  finance: '财务专员',
  ops: '运营专员',
}

type SidebarMode = 'chat' | 'work'

function resolveMode(path: string): SidebarMode {
  if (path.startsWith('/chat')) return 'chat'
  return 'work'
}

function isWorkItemActive(path: string, search: string, item: WorkbenchNavItem): boolean {
  if (item.match) return item.match(path, search)
  if (item.to === '/workbench/reconciliation') {
    return path === '/workbench/reconciliation'
  }
  return path === item.to || path.startsWith(item.to + '/')
}

function groupByDay(items: ConversationListItem[]) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const todayItems: ConversationListItem[] = []
  const olderItems: ConversationListItem[] = []
  for (const item of items) {
    const d = new Date(item.updated_at)
    d.setHours(0, 0, 0, 0)
    if (d.getTime() === today.getTime()) todayItems.push(item)
    else olderItems.push(item)
  }
  return { todayItems, olderItems }
}

export default function AppSidebar() {
  const location = useLocation()
  const navigate = useNavigate()
  const path = location.pathname
  const search = location.search
  const user = JSON.parse(localStorage.getItem('user') || '{}')
  const isAdmin = user.role === 'admin' || user.role === 'manager'
  const isOps = user.role === 'ops'
  const [reconOpen, setReconOpen] = useState(true)
  const [history, setHistory] = useState<ConversationListItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const { showModule, published } = usePublishedCenter()
  const workNavItems = WORKBENCH_NAV.filter((item) => showModule(item.moduleKey))

  const mode = resolveMode(path)
  const roleLabel = ROLE_LABELS[user.role] || user.display_name || user.username || '用户'
  const avatarChar = (user.display_name || user.username || '?').slice(0, 1)
  const activeConvId = new URLSearchParams(search).get('conversation_id')

  const loadHistory = useCallback(() => {
    if (isOps) return
    setHistoryLoading(true)
    getChatConversations(50)
      .then(setHistory)
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false))
  }, [isOps])

  useEffect(() => {
    if (!isOps) loadHistory()
  }, [isOps, loadHistory])

  useEffect(() => {
    if (mode === 'chat' && !isOps) loadHistory()
  }, [mode, isOps, loadHistory, search])

  useEffect(() => {
    const onRefresh = () => loadHistory()
    window.addEventListener('chat-history-refresh', onRefresh)
    return () => window.removeEventListener('chat-history-refresh', onRefresh)
  }, [loadHistory])

  const { todayItems, olderItems } = useMemo(() => groupByDay(history), [history])

  const openConversation = (item: ConversationListItem) => {
    const q = new URLSearchParams()
    if (item.task_id) q.set('task_id', item.task_id)
    if (item.difference_item_id) q.set('difference_id', item.difference_item_id)
    q.set('conversation_id', item.id)
    navigate(`/chat?${q.toString()}`)
  }

  const startNewChat = () => {
    navigate(`/chat?_new=${Date.now()}`, { replace: true })
  }

  const setMode = (m: SidebarMode) => {
    if (m === 'chat' && !isOps) navigate('/chat')
    else navigate('/workbench/reconciliation')
  }

  const logout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    navigate('/login')
  }

  const userMenuItems = [
    ...(isAdmin ? [{ key: 'admin', icon: <SettingOutlined />, label: '管理后台', onClick: () => navigate('/admin') }] : []),
    { type: 'divider' as const },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: logout },
  ]

  const renderHistoryItem = (item: ConversationListItem) => (
    <button
      key={item.id}
      type="button"
      className={`sidebar-history-item ${activeConvId === item.id ? 'active' : ''}`}
      onClick={() => openConversation(item)}
    >
      <span className="sidebar-history-title">{item.title}</span>
      <span className="sidebar-history-preview">{item.preview}</span>
    </button>
  )

  return (
    <aside className="app-sidebar">
      <div className="sidebar-scroll">
        <Link to="/workbench/reconciliation" className="sidebar-logo">
          <span className="sidebar-logo-mark">Y</span>
          <span className="sidebar-logo-text">
            <span className="sidebar-logo-title">亿流</span>
            <span className="sidebar-logo-sub">TECHNOLOGY</span>
          </span>
        </Link>

        <div className="sidebar-role-label">{roleLabel}</div>

        <div className="sidebar-mode-tabs">
          {!isOps && (
            <button
              type="button"
              className={`sidebar-mode-tab ${mode === 'chat' ? 'active' : ''}`}
              onClick={() => setMode('chat')}
            >
              对话
            </button>
          )}
          <button
            type="button"
            className={`sidebar-mode-tab ${mode === 'work' ? 'active' : ''}`}
            onClick={() => setMode('work')}
            style={isOps ? { flex: 1 } : undefined}
          >
            工作
          </button>
        </div>

        {mode === 'chat' && !isOps && (
          <>
            <button
              type="button"
              className="sidebar-new-chat"
              onClick={startNewChat}
            >
              <PlusOutlined /> 新对话
            </button>

            {isAdmin && (
              <nav className="sidebar-manage-nav" aria-label="平台配置">
                <Link
                  to="/chat/manage/agents"
                  className={`sidebar-manage-item${path.startsWith('/chat/manage/agents') ? ' active' : ''}`}
                >
                  <RobotOutlined className="sidebar-manage-item__icon" />
                  <span>智能体中心</span>
                </Link>
                <Link
                  to="/chat/manage/skills"
                  className={`sidebar-manage-item${path.startsWith('/chat/manage/skills') || path.startsWith('/chat/manage/assets') ? ' active' : ''}`}
                >
                  <ThunderboltOutlined className="sidebar-manage-item__icon" />
                  <span>技能中心</span>
                </Link>
              </nav>
            )}

            <div className="sidebar-history">
              <div className="sidebar-history-head">
                <HistoryOutlined />
                <span>历史对话</span>
                {history.length > 0 && <span className="sidebar-badge">{history.length}</span>}
              </div>
              {historyLoading ? (
                <div className="sidebar-history-loading"><Spin size="small" /></div>
              ) : history.length === 0 ? (
                <div className="sidebar-nav-hint">暂无记录，发送一条消息后会自动保存到此</div>
              ) : (
                <div className="sidebar-history-list">
                  {todayItems.length > 0 && (
                    <>
                      <div className="sidebar-history-label">今天</div>
                      {todayItems.map(renderHistoryItem)}
                    </>
                  )}
                  {olderItems.length > 0 && (
                    <>
                      <div className="sidebar-history-label">更早</div>
                      {olderItems.map(renderHistoryItem)}
                    </>
                  )}
                </div>
              )}
            </div>
          </>
        )}

        {mode === 'work' && (
          <div className="sidebar-nav-block">
            <button
              type="button"
              className="sidebar-group-head"
              onClick={() => setReconOpen((v) => !v)}
            >
              <span>收入核对中心</span>
              <DownOutlined className={`sidebar-chevron ${reconOpen ? 'open' : ''}`} />
            </button>
            {reconOpen && (
              <nav className="sidebar-subnav">
                {!published && (
                  <div className="sidebar-nav-hint">业务中心未发布，请先在管理后台发布</div>
                )}
                {workNavItems.map((item) => (
                  <Link
                    key={item.to}
                    to={item.to}
                    className={`sidebar-nav-item ${isWorkItemActive(path, location.search, item) ? 'active' : ''}`}
                  >
                    <span className="sidebar-nav-icon">{item.icon}</span>
                    {item.label}
                  </Link>
                ))}
                {published && workNavItems.length === 0 && (
                  <div className="sidebar-nav-hint">后台未启用工作台模块</div>
                )}
              </nav>
            )}
          </div>
        )}
      </div>

      <div className="sidebar-bottom">
        <Dropdown menu={{ items: userMenuItems }} trigger={['click']}>
          <button type="button" className="sidebar-user">
            <span className="sidebar-avatar">{avatarChar}</span>
            <span className="sidebar-user-name">{roleLabel}</span>
            <DownOutlined style={{ fontSize: 9, color: '#94a3b8' }} />
          </button>
        </Dropdown>
      </div>
    </aside>
  )
}
