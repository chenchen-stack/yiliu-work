import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Button, Spin, Table, Tag, Typography } from 'antd'
import { AdminRuleImportPanel } from './AdminRuleImportPanel'
import { SettingOutlined } from '@ant-design/icons'
import {
  getAdminBusinessCenter,
  getAdminBusinessCenters,
  getAdminCases,
  getAdminOntologyMapping,
  getAdminRules,
  getAdminSkills,
  type AdminRuleConfig,
  type BusinessCenter,
  type CaseAsset,
  type OntologyMapping,
} from '../api/client'
import { resolveAgentAsset, type AgentAssetPanelTarget } from '../utils/agentAssetConfig'
import { AdminLlmHub } from './AdminLlmHub'
import { AdminSemanticsPane } from './AdminSemanticsHub'
import type { AdminSkillRow } from './AdminSkillsPage'
import { KnowledgeBaseEmbed } from './KnowledgeBaseEmbed'
import { WorkflowSkillEmbed } from './WorkflowSkillEmbed'
import { WorkflowSummaryEmbed } from './WorkflowSummaryEmbed'

type Props = {
  assetKey: string
  onReload?: () => void
  onOpenInAssets: () => void
  onTraceSkill?: (skillId: string) => void
  onCreateRuleVersion?: () => void
}

export function AgentAssetConfigPanel({
  assetKey,
  onReload,
  onOpenInAssets,
  onTraceSkill,
  onCreateRuleVersion,
}: Props) {
  const target = resolveAgentAsset(assetKey)
  const [loading, setLoading] = useState(true)
  const [center, setCenter] = useState<BusinessCenter | null>(null)
  const [ontology, setOntology] = useState<OntologyMapping | null>(null)
  const [rules, setRules] = useState<AdminRuleConfig[]>([])
  const [skills, setSkills] = useState<AdminSkillRow[]>([])
  const [cases, setCases] = useState<CaseAsset[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const centers = await getAdminBusinessCenters()
      const cid = centers[0]?.id
      const [c, ont, r, sk, ca] = await Promise.all([
        cid ? getAdminBusinessCenter(cid) : Promise.resolve(null),
        getAdminOntologyMapping().catch(() => null),
        getAdminRules().catch(() => []),
        getAdminSkills().catch(() => []),
        getAdminCases().catch(() => []),
      ])
      setCenter(c)
      setOntology(ont)
      setRules(r)
      setSkills((sk || []) as AdminSkillRow[])
      setCases(ca || [])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, assetKey])

  const wrap = (child: ReactNode) => (
    <div className="agent-asset-panel__embed">{child}</div>
  )

  if (loading) {
    return (
      <div className="agent-asset-panel__loading">
        <Spin tip="加载能力资产…" />
      </div>
    )
  }

  if (target.kind === 'skill_group' && target.skillIds?.length) {
    return wrap(
      <div className="agent-asset-skill-group">
        <Typography.Paragraph type="secondary" className="agent-asset-skill-group__hint">
          以下 Skill 为 Agent 授权引用，可在 Skill 库中查看与编辑配置。
        </Typography.Paragraph>
        {target.skillIds.map((id) => {
          const sub = resolveAgentAsset(id)
          return (
            <div key={id} className="agent-asset-skill-group__item">
              <div>
                <Typography.Text strong>{sub.title}</Typography.Text>
                <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12 }}>
                  {sub.subtitle}
                </Typography.Text>
              </div>
              <Button
                size="small"
                icon={<SettingOutlined />}
                onClick={() => onTraceSkill?.(id)}
              >
                查看配置
              </Button>
            </div>
          )
        })}
      </div>,
    )
  }

  if (target.kind === 'knowledge_base' && target.kbId) {
    return wrap(
      <KnowledgeBaseEmbed kbId={target.kbId} cases={cases} onReload={() => { void load(); onReload?.() }} />,
    )
  }

  if (target.kind === 'llm') {
    return wrap(
      <div className="agent-asset-panel__llm">
        <AdminLlmHub onSaved={() => { void load(); onReload?.() }} />
      </div>,
    )
  }

  if (target.kind === 'rules' && center) {
    return wrap(
      <>
        <AdminRuleImportPanel
          ruleVersionId={center.rule_version_id}
          businessCenterId={center.id}
          versionLabel={center.rule_version_id?.slice(0, 8)}
          onCreateVersion={onCreateRuleVersion || (() => onReload?.())}
          onApplied={() => { void load(); onReload?.() }}
        />
        <Table
          className="admin-rules-table wf-node-panel__rules-table"
          dataSource={rules}
          rowKey="id"
          pagination={false}
          size="small"
          style={{ marginTop: 12 }}
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
      </>,
    )
  }

  if (target.kind === 'skill' && target.skillCode) {
    return wrap(
      <WorkflowSkillEmbed
        skillCode={target.skillCode}
        skills={skills}
        nodeLabel={target.title}
      />,
    )
  }

  if (target.kind === 'semantics' && target.semSub) {
    if (!ontology) {
      return <Typography.Text type="secondary">语义配置加载中…</Typography.Text>
    }
    return wrap(
      <AdminSemanticsPane
        sub={target.semSub}
        ontology={ontology}
        onSaved={() => { void load(); onReload?.() }}
      />,
    )
  }

  if (target.kind === 'workflow' && center) {
    return wrap(
      <WorkflowSummaryEmbed
        center={center}
        workflowId={target.workflowId}
        onOpenWorkflow={onOpenInAssets}
      />,
    )
  }

  return (
    <Typography.Text type="secondary">
      暂无法加载该资产配置，请使用「全屏编辑」前往能力资产页。
    </Typography.Text>
  )
}
