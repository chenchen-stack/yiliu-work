import { Navigate, useSearchParams } from 'react-router-dom'
import { Table, Tag } from 'antd'
import { ChatManageShell } from '../components/ChatManageShell'
import { AdminSemanticsHub, type SemanticsSubTab } from '../components/AdminSemanticsHub'
import { AdminLlmHub } from '../components/AdminLlmHub'
import { AdminRuleImportPanel } from '../components/AdminRuleImportPanel'
import { useAdminAssetBundle } from '../hooks/useAdminAssetBundle'

type AssetKey = 'semantics' | 'rules' | 'llm'

const TITLES: Record<AssetKey, { title: string; subtitle: string }> = {
  semantics: {
    title: '数据语义',
    subtitle: '数据接入 → 实体与规则 → 字段映射（与后台数据语义同源）',
  },
  rules: {
    title: '规则引擎',
    subtitle: '检测规则与业务中心绑定版本（与后台规则引擎同源）',
  },
  llm: {
    title: '大模型',
    subtitle: '平台模型路由与 Key（与后台大模型中心同源）',
  },
}

export default function ChatManageAsset({ assetKey }: { assetKey: AssetKey }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const user = JSON.parse(localStorage.getItem('user') || '{}')
  const isAdmin = user.role === 'admin' || user.role === 'manager'

  const {
    center,
    ontology,
    rules,
    loading,
    error,
    reload,
  } = useAdminAssetBundle()

  if (!isAdmin) return <Navigate to="/chat" replace />

  const meta = TITLES[assetKey]
  const semParam = searchParams.get('sem') as SemanticsSubTab | null
  const semSub: SemanticsSubTab = semParam && ['datasources', 'entities', 'mapping', 'graph'].includes(semParam)
    ? semParam
    : 'datasources'

  return (
    <ChatManageShell
      title={meta.title}
      loading={loading}
      error={error}
      onRetry={reload}
      fullWidth
      minimal
    >
      {assetKey === 'semantics' && ontology && center && (
        <AdminSemanticsHub
          ontology={ontology}
          activeSubTab={semSub}
          onSubTabChange={(key) => setSearchParams({ sem: key })}
          onSaved={() => void reload()}
        />
      )}

      {assetKey === 'llm' && (
        <AdminLlmHub onSaved={() => void reload()} />
      )}

      {assetKey === 'rules' && center && (
        <>
          <AdminRuleImportPanel
            ruleVersionId={center.rule_version_id}
            businessCenterId={center.id}
            versionLabel={center.rule_version_id?.slice(0, 8)}
            onCreateVersion={() => void reload()}
            onApplied={() => void reload()}
          />
          <Table
            className="admin-rules-table"
            style={{ marginTop: 12 }}
            dataSource={rules}
            rowKey="id"
            pagination={false}
            size="small"
            columns={[
              { title: '规则', dataIndex: 'name', ellipsis: true },
              { title: '类型', dataIndex: 'rule_type', width: 100 },
              {
                title: '状态',
                width: 72,
                render: (_, r) => (
                  <Tag color={r.enabled ? 'success' : 'default'} bordered={false}>
                    {r.enabled ? '启用' : '停用'}
                  </Tag>
                ),
              },
            ]}
          />
        </>
      )}
    </ChatManageShell>
  )
}
