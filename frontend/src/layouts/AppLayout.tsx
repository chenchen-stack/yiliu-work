import { Layout, Breadcrumb } from 'antd'
import { Link, Outlet, useLocation } from 'react-router-dom'
import AppSidebar from '../components/AppSidebar'
import { PublishedCenterProvider } from '../context/PublishedCenterContext'

const { Content } = Layout

export default function AppLayout() {
  const path = useLocation().pathname
  const isChatManage = path.startsWith('/chat/manage')
  const isChat = path.startsWith('/chat') && !isChatManage
  const isAdmin = path.startsWith('/admin')

  return (
    <Layout className={`app-shell app-shell-v2${isAdmin ? ' app-shell-admin' : ''}`}>
      <PublishedCenterProvider>
      {!isAdmin && <AppSidebar />}
      <Layout className="app-main app-main-v2">
        <Content
          className={
            isAdmin
              ? 'app-content app-content-admin'
              : isChatManage
                ? 'app-content app-content-manage'
                : isChat
                  ? 'app-content app-content-chat'
                  : 'app-content'
          }
        >
          {path.startsWith('/workbench') && path !== '/workbench/reconciliation' && (
            <Breadcrumb
              className="app-breadcrumb"
              items={[
                { title: <Link to="/workbench/reconciliation">收入对账中心</Link> },
                { title: path.includes('/tasks/new') ? '新建对账' : path.includes('/tasks/') ? '任务详情' : '工作台' },
              ]}
            />
          )}
          <Outlet />
        </Content>
      </Layout>
      </PublishedCenterProvider>
    </Layout>
  )
}
