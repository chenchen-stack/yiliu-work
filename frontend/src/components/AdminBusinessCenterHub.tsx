import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Divider, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  DatabaseOutlined, RocketOutlined, RollbackOutlined, StopOutlined,
} from '@ant-design/icons'
import type {
  AdminRuleConfig, AgentConfigItem, BusinessCenter, OntologyMapping, WorkflowNode,
} from '../api/client'
import { ensureWorkflowNodes } from '../utils/workflowNodes'
import { buildBusinessCenterTree, type BcNestAction, type BcTreeRow } from '../utils/businessCenterNest'
import { buildAdminTabUrl, resolveAgentAsset } from '../utils/agentAssetConfig'
import type { AdminSkillRow } from './AdminSkillsPage'
import { AgentAssetConfigModal } from './AgentAssetConfigModal'
import { WorkflowNodeConfigModal } from './WorkflowNodeConfigModal'

const STATUS_LABEL: Record<string, string> = {
  draft: '草稿', testing: '测试中', published: '已发布', offline: '已下架',
}

const STATUS_CLASS: Record<string, string> = {
  draft: 'bc-hub__tag--draft',
  testing: 'bc-hub__tag--testing',
  published: 'bc-hub__tag--published',
  offline: 'bc-hub__tag--offline',
}

type Props = {
  center: BusinessCenter
  ontology: OntologyMapping | null
  rules: AdminRuleConfig[]
  agents: AgentConfigItem[]
  onReload: () => void
  onNavigate: (tab: string, skillCode?: string, semSub?: string) => void
  onCreateRuleVersion: () => void
  onPublish: () => void
  onRollback: () => void
  onOffline: () => void
}

export function AdminBusinessCenterHub({
  center,
  ontology,
  rules,
  agents,
  onReload,
  onNavigate,
  onCreateRuleVersion,
  onPublish,
  onRollback,
  onOffline,
}: Props) {
  const navigate = useNavigate()
  const [assetKey, setAssetKey] = useState<string | null>(null)
  const [configNodeId, setConfigNodeId] = useState<string | null>(null)

  const wfNodes = useMemo(
    () => ensureWorkflowNodes((center.workflow?.nodes || []) as WorkflowNode[]),
    [center.workflow?.nodes],
  )

  const configNode = useMemo(
    () => wfNodes.find((n) => n.id === configNodeId) || null,
    [wfNodes, configNodeId],
  )

  const treeData = useMemo(
    () => buildBusinessCenterTree(center, ontology, rules, agents),
    [center, ontology, rules, agents],
  )

  const skillRows = (center.skills || []) as AdminSkillRow[]

  const handleNestAction = (action: BcNestAction) => {
    if (action.type === 'workflow_node') {
      setConfigNodeId(action.nodeId)
      return
    }
    if (action.type === 'asset') {
      setAssetKey(action.assetKey)
      return
    }
    if (action.type === 'navigate') {
      onNavigate(action.tab, action.skill, action.semSub)
    }
  }

  const NODE_FULLSCREEN_ASSET: Record<string, string> = {
    import: 'bc-sem-datasources',
    mapping: 'bc-sem-mapping',
    ontology: 'bc-sem-entities',
    detect: 'bc-rules',
    ai_explain: 'bc-llm',
  }

  const openAssetFullscreen = (key: string) => {
    navigate(buildAdminTabUrl(resolveAgentAsset(key)))
    setAssetKey(null)
  }

  const openNodeFullscreen = () => {
    if (!configNode) return
    const preset = NODE_FULLSCREEN_ASSET[configNode.id]
    if (preset) {
      const t = resolveAgentAsset(preset)
      onNavigate(t.adminTab, undefined, t.semSub)
    } else if (configNode.skill_code || configNode.skill) {
      onNavigate('skills', configNode.skill_code || configNode.skill)
    } else {
      onNavigate('workflow')
    }
    setConfigNodeId(null)
  }

  const columns: ColumnsType<BcTreeRow> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      ellipsis: true,
      render: (name: string, record) => (
        <span className={record.action ? 'bc-tree__name bc-tree__name--link' : 'bc-tree__name'}>
          {name}
        </span>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 100,
      render: (type: string) => <span className="bc-tree__type">{type}</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status?: string) => status || '—',
    },
    {
      title: '说明',
      dataIndex: 'remark',
      key: 'remark',
      ellipsis: true,
      render: (remark?: string) => (
        <span className="bc-tree__remark">{remark || '—'}</span>
      ),
    },
    {
      title: '',
      key: 'action',
      width: 72,
      align: 'right',
      render: (_: unknown, record) => (
        record.action ? (
          <Button
            type="link"
            size="small"
            className="bc-tree__action"
            onClick={(e) => {
              e.stopPropagation()
              handleNestAction(record.action!)
            }}
          >
            配置
          </Button>
        ) : null
      ),
    },
  ]

  return (
    <div className="bc-hub">
      <div className="bc-hub__bar">
        <div className="bc-hub__bar-main">
          <DatabaseOutlined className="bc-hub__bar-icon" />
          <div className="bc-hub__bar-info">
            <div className="bc-hub__bar-title-row">
              <Typography.Title level={5} className="bc-hub__bar-title">
                {center.name}
              </Typography.Title>
              <span className={`bc-hub__tag ${STATUS_CLASS[center.status] || ''}`}>
                {STATUS_LABEL[center.status] || center.status}
              </span>
              <span className="bc-hub__tag bc-hub__tag--version">v{center.version}</span>
            </div>
            <Typography.Text type="secondary" className="bc-hub__bar-meta">
              {center.code} · 规则 v{center.rule_version?.version ?? '—'}
              {' · '}{center.workflow?.name} v{center.workflow?.version ?? 1}
            </Typography.Text>
          </div>
        </div>
        {center.status !== 'published' && (
          <span className="bc-hub__bar-hint">
            {STATUS_LABEL[center.status] || center.status} · 发布后前台生效
          </span>
        )}
        <Divider type="vertical" className="bc-hub__bar-divider" />
        <div className="bc-hub__bar-actions">
          <Button
            type="primary"
            size="small"
            className="bc-hub__btn-primary"
            icon={<RocketOutlined />}
            onClick={onPublish}
            disabled={center.status === 'published'}
          >
            发布
          </Button>
          <Button type="text" size="small" className="bc-hub__btn-text" icon={<RollbackOutlined />} onClick={onRollback}>
            回滚
          </Button>
          <Button
            type="text"
            size="small"
            className="bc-hub__btn-text"
            icon={<StopOutlined />}
            onClick={onOffline}
            disabled={center.status === 'offline'}
          >
            下架
          </Button>
        </div>
      </div>

      <Table<BcTreeRow>
        className="bc-tree"
        columns={columns}
        dataSource={treeData}
        rowKey="key"
        pagination={false}
        size="middle"
        expandable={{
          defaultExpandAllRows: true,
          indentSize: 20,
        }}
        onRow={(record) => ({
          onClick: () => {
            if (record.action) handleNestAction(record.action)
          },
          className: record.action ? 'bc-tree__row--clickable' : undefined,
        })}
      />

      <WorkflowNodeConfigModal
        open={!!configNode}
        node={configNode}
        ontology={ontology}
        center={center}
        rules={rules}
        skills={skillRows}
        onClose={() => setConfigNodeId(null)}
        onReload={onReload}
        onCreateRuleVersion={onCreateRuleVersion}
        onOpenInAssets={openNodeFullscreen}
      />

      <AgentAssetConfigModal
        open={!!assetKey}
        assetKey={assetKey}
        onClose={() => setAssetKey(null)}
        onOpenInAssets={openAssetFullscreen}
        onTraceSkill={setAssetKey}
        onCreateRuleVersion={onCreateRuleVersion}
      />
    </div>
  )
}
