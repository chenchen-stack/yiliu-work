import { useEffect, useMemo, useState } from 'react'
import { Spin, Tag, Tabs, Typography } from 'antd'
import {
  BranchesOutlined, CodeOutlined, ExperimentOutlined, FileTextOutlined,
  SettingOutlined, ThunderboltOutlined, RobotOutlined,
} from '@ant-design/icons'
import {
  getSkillPackage,
  type SkillPackageDetail,
} from '../api/client'
import type { AdminSkillRow } from '../types/adminSkill'
import { SkillCardExpandPanel } from './SkillCardExpand'
import { SkillStructuredTest } from './SkillStructuredTest'
import { SkillTestChat } from './SkillTestChat'

const SKILL_TYPE_LABEL: Record<string, string> = {
  ability: '能力型',
  knowledge: '知识型',
  process: '流程型',
  flow: '流程型',
}

const SKILL_META: Record<string, { desc: string }> = {
  data_import: { desc: '读取任务绑定的业务侧 / 财务侧数据源，解析 Excel 并写入执行上下文。' },
  field_mapping: { desc: '按字段映射配置翻译列名、生成匹配键，供差异识别使用。' },
  ontology_context: { desc: '加载已发布实体与领域规则到任务上下文，不产出差异。' },
  difference_detect: { desc: '执行检测规则，产出差异事实清单（不由大模型判定）。' },
  anomaly_explain: { desc: '对每条差异调用大模型（DeepSeek）生成归因、证据与处理建议。' },
  review_flow: { desc: '财务人工确认 / 退回 / 指派处理，Workflow 人工节点。' },
  re_verify: { desc: '修正数据后重跑规则，验证差异是否清零。' },
  report_gen: { desc: '生成 PDF 核对报告并支持任务关闭。' },
}

function skillIcon(type?: string) {
  if (type === 'knowledge') return <RobotOutlined />
  if (type === 'process') return <BranchesOutlined />
  return <ThunderboltOutlined />
}

export function SkillPackagePanel({
  skillCode,
  skillRow,
  nodeLabel,
  pkgDetail,
  setPkgDetail,
  embedded = false,
  modalMode = false,
  onConfig,
}: {
  skillCode: string
  skillRow: AdminSkillRow
  nodeLabel?: string
  pkgDetail: SkillPackageDetail | null
  setPkgDetail: (d: SkillPackageDetail | null) => void
  embedded?: boolean
  /** 技能库居中弹窗：隐藏重复标题，默认打开对话测试 */
  modalMode?: boolean
  onConfig?: () => void
}) {
  const [loadingPkg, setLoadingPkg] = useState(false)
  const [activeTab, setActiveTab] = useState('test')

  const canStructured = Boolean(
    pkgDetail?.has_executor || pkgDetail?.platform_executable,
  )

  useEffect(() => {
    if (!skillCode) return
    setLoadingPkg(true)
    setActiveTab('test')
    getSkillPackage(skillCode)
      .then((d) => setPkgDetail(d))
      .catch(() => setPkgDetail(null))
      .finally(() => setLoadingPkg(false))
  }, [skillCode, setPkgDetail])

  const tabItems = useMemo(() => {
    if (!pkgDetail) return []
    const items = [
      {
        key: 'test',
        label: (
          <span className="skill-pkg-tab-label">
            <ExperimentOutlined /> 对话测试
          </span>
        ),
        children: (
          <div className="skill-pkg-tab-pane skill-pkg-tab-pane--chat">
            <Typography.Paragraph type="secondary" className="skill-pkg-tab-hint">
              自然语言描述场景，后端 SkillTestAgent 会规划并调用 Skill（SSE：
              <code>/api/v1/skill-test/sessions/…/chat</code>
              ）。建议先在「工作台」创建对账任务以绑定真实数据。
            </Typography.Paragraph>
            <SkillTestChat
              embedded
              focusSkill={skillCode}
              skillName={pkgDetail.name || skillRow.name}
            />
          </div>
        ),
      },
      {
        key: 'files',
        label: (
          <span className="skill-pkg-tab-label">
            <FileTextOutlined /> 标准文件
          </span>
        ),
        children: (
          <SkillCardExpandPanel
            skill={skillRow}
            onConfig={onConfig}
          />
        ),
      },
    ]
    if (canStructured) {
      items.push({
        key: 'structured',
        label: (
          <span className="skill-pkg-tab-label">
            <ThunderboltOutlined /> 结构化测试
          </span>
        ),
        children: <SkillStructuredTest skillCode={skillCode} pkg={pkgDetail} />,
      })
    }
    if (pkgDetail.skill_md && !modalMode) {
      items.push({
        key: 'doc',
        label: (
          <span className="skill-pkg-tab-label">
            <CodeOutlined /> 说明书
          </span>
        ),
        children: <pre className="skill-pkg-md">{pkgDetail.skill_md}</pre>,
      })
    }
    items.push({
      key: 'schema',
      label: (
        <span className="skill-pkg-tab-label">
          <SettingOutlined /> 接口
        </span>
      ),
      children: (
        <div className="skill-pkg-schema">
          <div className="skill-pkg-schema__section">
            <Typography.Text strong style={{ fontSize: 13 }}>
              <span style={{ color: '#10b981' }}>▸</span> 输入 Schema
            </Typography.Text>
            <pre className="skill-pkg-schema__code">
              {JSON.stringify(pkgDetail.input_schema, null, 2)}
            </pre>
          </div>
          <div className="skill-pkg-schema__section">
            <Typography.Text strong style={{ fontSize: 13 }}>
              <span style={{ color: '#3b82f6' }}>▸</span> 输出 Schema
            </Typography.Text>
            <pre className="skill-pkg-schema__code">
              {JSON.stringify(pkgDetail.output_schema, null, 2)}
            </pre>
          </div>
          {pkgDetail.config_schema && Object.keys(pkgDetail.config_schema).length > 0 && (
            <div className="skill-pkg-schema__section skill-pkg-schema__section--full">
              <Typography.Text strong style={{ fontSize: 13 }}>
                <span style={{ color: '#f59e0b' }}>▸</span> config.yaml
              </Typography.Text>
              <pre className="skill-pkg-schema__code">
                {JSON.stringify(pkgDetail.config_schema, null, 2)}
              </pre>
            </div>
          )}
        </div>
      ),
    })
    return items
  }, [pkgDetail, skillCode, skillRow, canStructured, modalMode, onConfig])

  if (loadingPkg) {
    return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
  }

  const showHero = !embedded && !modalMode

  return (
    <div className={`skill-pkg-panel${embedded ? ' skill-pkg-panel--embedded' : ''}${modalMode ? ' skill-pkg-panel--modal' : ''}`}>
      {showHero && (
        <>
          <div className="skill-pkg-hero">
            <div className="skill-pkg-hero__icon">{skillIcon(skillRow.type)}</div>
            <div className="skill-pkg-hero__text">
              <Typography.Title level={5} style={{ margin: 0 }}>
                {pkgDetail?.name || skillRow.name || skillCode}
              </Typography.Title>
              <Typography.Text type="secondary">
                {pkgDetail?.description || SKILL_META[skillCode]?.desc || ''}
              </Typography.Text>
            </div>
          </div>
          <div className="skill-pkg-stats">
            <Tag><CodeOutlined /> {skillCode}</Tag>
            <Tag>{SKILL_TYPE_LABEL[(pkgDetail?.type || skillRow.type) || 'ability']}</Tag>
            <Tag>v{pkgDetail?.version ?? skillRow.version ?? 1}</Tag>
            {nodeLabel && <Tag color="blue"><BranchesOutlined /> {nodeLabel}</Tag>}
            {pkgDetail?.has_executor && <Tag color="green">可执行</Tag>}
            {pkgDetail?.platform_executable && !pkgDetail?.has_executor && (
              <Tag color="blue">平台执行</Tag>
            )}
          </div>
        </>
      )}

      {pkgDetail && tabItems.length > 0 && (
        <Tabs
          className="skill-pkg-tabs skill-pkg-tabs--primary"
          size={modalMode || embedded ? 'middle' : 'large'}
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
        />
      )}

      {!pkgDetail && !loadingPkg && (
        <div className="admin-skill-detail">
          <div className="admin-skill-detail__stats">
            <div><span>标识</span><Typography.Text code>{skillRow.code}</Typography.Text></div>
            <div><span>版本</span><strong>v{skillRow.version ?? 1}</strong></div>
            <div><span>状态</span><strong>{skillRow.status || 'published'}</strong></div>
            <div><span>Workflow 节点</span><strong>{nodeLabel || '—'}</strong></div>
          </div>
          <Typography.Paragraph>{SKILL_META[skillCode]?.desc || '—'}</Typography.Paragraph>
        </div>
      )}
    </div>
  )
}
