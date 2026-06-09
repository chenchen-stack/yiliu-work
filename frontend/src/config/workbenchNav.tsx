import { HomeOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { PAGE_MODULE_KEYS } from '../utils/pageModules'

export interface WorkbenchNavItem {
  to: string
  label: string
  icon: React.ReactNode
  moduleKey: string
  match?: (path: string, search: string) => boolean
}

/** MVP 工作台侧栏：仅今日摘要 + 核对任务列表 */
export const WORKBENCH_NAV: WorkbenchNavItem[] = [
  {
    to: '/workbench/reconciliation',
    label: '今日摘要',
    icon: <HomeOutlined />,
    moduleKey: PAGE_MODULE_KEYS.todaySummary,
  },
  {
    to: '/workbench/reconciliation/tasks',
    label: '核对任务',
    icon: <UnorderedListOutlined />,
    moduleKey: PAGE_MODULE_KEYS.taskBatches,
    match: (p) => p.includes('/tasks') && !p.includes('new'),
  },
]
