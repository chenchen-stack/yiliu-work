import { useCallback, useEffect, useState } from 'react'
import { Button, Dropdown, message, Switch, Typography, Upload } from 'antd'
import type { MenuProps } from 'antd'
import { DownOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import {
  applyTroubleshootingPreset,
  bindRulesToOntology,
  bindRulesToWorkflow,
  getTroubleshootingPreset,
  importTroubleshootingExcel,
  type TroubleshootingPreset,
} from '../api/client'
import { formatApiError } from '../api/errors'

type Props = {
  ruleVersionId?: string
  businessCenterId?: string
  versionLabel?: string
  onCreateVersion: () => void
  onApplied: () => void
}

export function AdminRuleImportPanel({
  ruleVersionId,
  businessCenterId,
  versionLabel,
  onCreateVersion,
  onApplied,
}: Props) {
  const [preset, setPreset] = useState<TroubleshootingPreset | null>(null)
  const [busy, setBusy] = useState(false)
  const [useAi, setUseAi] = useState(false)
  const [showPreview, setShowPreview] = useState(false)

  const loadPreset = useCallback(() => {
    getTroubleshootingPreset()
      .then(setPreset)
      .catch(() => setPreset(null))
  }, [])

  useEffect(() => { loadPreset() }, [loadPreset])

  const formatBindSummary = (res: { workflow_bind?: { bound_count?: number } | null; ontology_bind?: { bound_count?: number } | null; applied: unknown[] }) => {
    const wf = res.workflow_bind?.bound_count ?? 0
    const onto = res.ontology_bind?.bound_count ?? 0
    const parts = [`已更新 ${res.applied.length} 条检测规则`]
    if (onto > 0) parts.push(`绑定本体 ${onto} 条`)
    if (wf > 0) parts.push(`同步 Workflow ${wf} 条`)
    return parts.join('，')
  }

  const handleBindOntology = async () => {
    if (!ruleVersionId) {
      message.warning('未找到当前规则版本')
      return
    }
    setBusy(true)
    try {
      const res = await bindRulesToOntology(ruleVersionId, businessCenterId)
      const n = res.ontology_bind?.bound_count ?? res.applied.length
      message.success(`已绑定 ${n} 条规则到「数据语义 → 领域规则」`)
      onApplied()
    } catch (e) {
      message.error(formatApiError(e, '绑定失败'))
    } finally {
      setBusy(false)
    }
  }

  const handleBindWorkflow = async () => {
    if (!ruleVersionId) {
      message.warning('未找到当前规则版本')
      return
    }
    setBusy(true)
    try {
      const res = await bindRulesToWorkflow(ruleVersionId, businessCenterId)
      const n = res.workflow_bind?.bound_count ?? res.applied.length
      message.success(`已同步 ${n} 条规则到 Workflow「差异识别」节点`)
      onApplied()
    } catch (e) {
      message.error(formatApiError(e, '同步失败'))
    } finally {
      setBusy(false)
    }
  }

  const handleApplyPreset = async () => {
    if (!ruleVersionId) {
      message.warning('未找到当前规则版本')
      return
    }
    setBusy(true)
    try {
      const res = await applyTroubleshootingPreset(ruleVersionId, businessCenterId)
      message.success(
        `${formatBindSummary(res)}（${res.total_patterns} 条登记表场景）`,
        6,
      )
      onApplied()
    } catch (e) {
      message.error(formatApiError(e, '应用失败'))
    } finally {
      setBusy(false)
    }
  }

  const uploadProps: UploadProps = {
    accept: '.xlsx,.xls',
    showUploadList: false,
    maxCount: 1,
    disabled: !ruleVersionId || busy,
    beforeUpload: (file) => {
      if (!ruleVersionId) return Upload.LIST_IGNORE
      setBusy(true)
      importTroubleshootingExcel(file, {
        rule_version_id: ruleVersionId,
        business_center_id: businessCenterId,
        apply: true,
        use_ai: useAi,
      })
        .then((res) => {
          message.success(
            `已识别 ${res.total_patterns} 条登记表场景，${formatBindSummary(res)}`,
            6,
          )
          onApplied()
          loadPreset()
        })
        .catch((e) => message.error(formatApiError(e, '识别失败')))
        .finally(() => setBusy(false))
      return false
    },
  }

  const moreItems: MenuProps['items'] = [
    {
      key: 'preview',
      label: showPreview ? '收起规则摘要' : '查看规则摘要',
      onClick: () => setShowPreview((v) => !v),
    },
    {
      key: 'ai',
      label: (
        <span onClick={(e) => e.stopPropagation()}>
          AI 精炼
          <Switch size="small" checked={useAi} onChange={setUseAi} style={{ marginLeft: 8 }} />
        </span>
      ),
    },
    {
      key: 'bind-ontology',
      label: '绑定到数据语义（领域规则）',
      onClick: handleBindOntology,
    },
    {
      key: 'bind',
      label: '同步到 Workflow',
      onClick: handleBindWorkflow,
    },
    { type: 'divider' },
    {
      key: 'version',
      label: '创建新版本',
      onClick: onCreateVersion,
    },
  ]

  const patternCount = preset?.total_patterns

  return (
    <div className="admin-rules-head">
      <div className="admin-rules-head__main">
        <Typography.Text type="secondary" className="admin-rules-head__meta">
          方太登记表排查规则（上传 Excel 后自动绑定「数据语义 → 领域规则」）
          {patternCount != null && <> · 已提炼 {patternCount} 条场景</>}
          {versionLabel && <> · 版本 {versionLabel}</>}
          {' · '}新建核对任务将自动使用本版规则
        </Typography.Text>
        <div className="admin-rules-head__actions">
          <Button type="primary" loading={busy} disabled={!ruleVersionId} onClick={handleApplyPreset}>
            应用登记表规则
          </Button>
          <Upload {...uploadProps}>
            <Button loading={busy} disabled={!ruleVersionId}>上传 Excel</Button>
          </Upload>
          <Dropdown menu={{ items: moreItems }} trigger={['click']}>
            <Button type="text" icon={<DownOutlined />}>更多</Button>
          </Dropdown>
        </div>
      </div>

      {showPreview && preset?.consolidated_rules?.length ? (
        <div className="admin-rules-preview">
          {preset.consolidated_rules.map((r) => (
            <div key={r.rule_type} className="admin-rules-preview__item">
              <Typography.Text strong style={{ fontSize: 13 }}>{r.name}</Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
                {r.sample_count} 条场景 · {r.condition.slice(0, 80)}
                {r.condition.length > 80 ? '…' : ''}
              </Typography.Text>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
