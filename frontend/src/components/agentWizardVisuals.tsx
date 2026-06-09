import type { ReactNode } from 'react'
import { LlmProviderLogo } from './LlmProviderLogo'
import { DatasourceBrandIcon } from '../utils/datasourceBranding'
import {
  BookOutlined, BranchesOutlined,
  CheckCircleOutlined, CloudOutlined, EditOutlined,
  ExperimentOutlined, FileSearchOutlined, FileTextOutlined, NodeIndexOutlined,
  RobotOutlined, StopOutlined, SwapOutlined, ThunderboltOutlined,
  UnorderedListOutlined, AimOutlined, ClockCircleOutlined, RightOutlined,
} from '@ant-design/icons'

export type WizardIconTone =
  | 'orange' | 'blue' | 'green' | 'purple' | 'indigo' | 'slate' | 'rose' | 'cyan' | 'amber'

export function WizardOptionIcon({ tone, children }: { tone: WizardIconTone; children: ReactNode }) {
  return (
    <div className={`agent-wizard-opt-icon agent-wizard-opt-icon--${tone}`} aria-hidden>
      {children}
    </div>
  )
}

export const WIZARD_MODEL_ICONS: Record<string, { icon: ReactNode; tone: WizardIconTone }> = {
  'mock-ai': { icon: <ExperimentOutlined />, tone: 'purple' },
  'deepseek-v4-pro': { icon: <LlmProviderLogo provider="deepseek" size={28} />, tone: 'blue' },
  deepseek: { icon: <LlmProviderLogo provider="deepseek" size={28} />, tone: 'blue' },
}

export function WizardDeepSeekLogo({ size = 28 }: { size?: number }) {
  return <LlmProviderLogo provider="deepseek" size={size} />
}

export const WIZARD_SKILL_ICONS: Record<string, { icon: ReactNode; tone: WizardIconTone }> = {
  'skill-anomaly_explain': { icon: <FileSearchOutlined />, tone: 'amber' },
  'skill-query_tasks': { icon: <UnorderedListOutlined />, tone: 'blue' },
}

export const WIZARD_DS_ICONS: Record<string, { icon: ReactNode; tone: WizardIconTone }> = {
  sap_billing: { icon: <DatasourceBrandIcon catalog="sap" size={28} showEngine={false} />, tone: 'indigo' },
  dms_ledger: { icon: <DatasourceBrandIcon catalog="dms" size={28} showEngine={false} />, tone: 'green' },
  fanruan_platform: { icon: <DatasourceBrandIcon catalog="fanruan" size={28} showEngine={false} />, tone: 'blue' },
}

export const WIZARD_STATUS_ICONS: Record<string, { icon: ReactNode; tone: WizardIconTone }> = {
  draft: { icon: <FileTextOutlined />, tone: 'slate' },
  pending_review: { icon: <ClockCircleOutlined />, tone: 'amber' },
  published: { icon: <CheckCircleOutlined />, tone: 'green' },
  offline: { icon: <StopOutlined />, tone: 'rose' },
}

export function OriginPresetVisual() {
  return (
    <div className="agent-wizard-origin-visual">
      <div className="agent-wizard-origin-visual__flow">
        <span className="agent-wizard-mini-badge agent-wizard-mini-badge--sap">
          <DatasourceBrandIcon catalog="sap" size={16} showEngine={false} /> SAP
        </span>
        <SwapOutlined className="agent-wizard-origin-visual__swap" />
        <span className="agent-wizard-mini-badge agent-wizard-mini-badge--dms">
          <DatasourceBrandIcon catalog="dms" size={16} showEngine={false} /> DMS
        </span>
      </div>
      <div className="agent-wizard-origin-visual__chips">
        <span><ThunderboltOutlined /> 双 Skill</span>
        <span><BookOutlined /> 案例库</span>
        <span><BranchesOutlined /> 核对流</span>
      </div>
    </div>
  )
}

export function OriginBlankVisual() {
  return (
    <WizardOptionIcon tone="slate">
      <EditOutlined />
    </WizardOptionIcon>
  )
}

export function FixedAssetPanel({
  tone,
  icon,
  title,
  tag,
  desc,
  onTrace,
}: {
  tone: WizardIconTone
  icon: ReactNode
  title: string
  tag?: ReactNode
  desc: string
  onTrace?: () => void
}) {
  return (
    <div className={`agent-wizard-asset-panel${onTrace ? ' agent-wizard-asset-panel--traceable' : ''}`}>
      <div className="agent-wizard-asset-panel__head">
        <WizardOptionIcon tone={tone}>{icon}</WizardOptionIcon>
        <div className="agent-wizard-asset-panel__head-text">
          <div className="agent-wizard-asset-panel__title-row">
            <span className="agent-wizard-asset-panel__title">{title}</span>
            {tag}
          </div>
          <p className="agent-wizard-asset-panel__desc">{desc}</p>
        </div>
        {onTrace && (
          <button type="button" className="agent-wizard-asset-panel__trace" onClick={onTrace}>
            查看配置
          </button>
        )}
      </div>
    </div>
  )
}

export function SummaryRow({
  tone,
  icon,
  label,
  value,
  onTrace,
}: {
  tone: WizardIconTone
  icon: ReactNode
  label: string
  value: string
  onTrace?: () => void
}) {
  const cls = `agent-wizard-summary-row${onTrace ? ' agent-wizard-summary-row--traceable' : ''}`
  const inner = (
    <>
      <WizardOptionIcon tone={tone}>{icon}</WizardOptionIcon>
      <div className="agent-wizard-summary-row__body">
        <span className="agent-wizard-summary-row__label">{label}</span>
        <span className="agent-wizard-summary-row__value">{value}</span>
      </div>
      {onTrace && (
        <span className="agent-wizard-summary-row__action">
          查看配置
          <RightOutlined />
        </span>
      )}
    </>
  )
  if (onTrace) {
    return (
      <button type="button" className={cls} onClick={onTrace}>
        {inner}
      </button>
    )
  }
  return <div className={cls}>{inner}</div>
}

export function ModelRouteHint({
  runtimeReady,
  platformModel,
  useMock,
}: {
  runtimeReady?: boolean
  platformModel?: string
  useMock?: boolean
}) {
  if (runtimeReady && platformModel) {
    return (
      <span className="agent-wizard-section-hint agent-wizard-section-hint--ok">
        <CloudOutlined /> 已联动大模型中心 · {platformModel} · 运行中
      </span>
    )
  }
  if (useMock) {
    return (
      <span className="agent-wizard-section-hint agent-wizard-section-hint--warn">
        <CloudOutlined /> 大模型中心为模拟模式，选 DeepSeek 也不会真实调用
      </span>
    )
  }
  return (
    <span className="agent-wizard-section-hint">
      <CloudOutlined /> 请在大模型中心配置 API Key 并关闭模拟模式
    </span>
  )
}

export const KB_PANEL_ICON = <BookOutlined />
export const WF_PANEL_ICON = <NodeIndexOutlined />
export const TARGET_ICON = <AimOutlined />
export const TABLE_PAIR_ICON = <SwapOutlined />
export const SKILL_SUMMARY_ICON = <ThunderboltOutlined />
export const KB_SUMMARY_ICON = <BookOutlined />
export const WF_SUMMARY_ICON = <BranchesOutlined />
export const MODEL_SUMMARY_ICON = <RobotOutlined />
