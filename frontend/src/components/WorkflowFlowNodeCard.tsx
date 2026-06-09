import type { PointerEvent as ReactPointerEvent } from 'react'
import { CloseOutlined, HolderOutlined, RightOutlined } from '@ant-design/icons'
import { Switch } from 'antd'
import type { WorkflowNode } from '../api/client'
import type { WorkflowNodeInsight } from '../utils/workflowNodeInsights'
import { LAYOUT_NODE_W } from '../utils/workflowNodeLayout'
import { templateForNodeId } from '../utils/workflowNodeCatalog'

type Props = {
  node: WorkflowNode
  index: number
  insight: WorkflowNodeInsight
  locked: boolean
  selected: boolean
  dragging: boolean
  configLabel?: string
  onToggle: (enabled: boolean) => void
  onSelect: () => void
  onDragStart: (e: ReactPointerEvent) => void
  onRemove?: () => void
}

function nodeRoleClass(id: string): 'system' | 'ai' | 'human' {
  const t = templateForNodeId(id)
  if (t?.role === 'ai' || id === 'ai_explain') return 'ai'
  if (t?.role === 'human' || id === 'review') return 'human'
  return 'system'
}

export function WorkflowFlowNodeCard({
  node,
  index,
  insight,
  locked,
  selected,
  dragging,
  configLabel,
  onToggle,
  onSelect,
  onDragStart,
  onRemove,
}: Props) {
  const on = node.enabled !== false
  const role = nodeRoleClass(node.id)
  const cfgLabel = configLabel || '配置'

  return (
    <div
      className={[
        'wf-card',
        `wf-card--${role}`,
        on ? '' : 'wf-card--off',
        selected ? 'wf-card--selected' : '',
        dragging ? 'wf-card--drag' : '',
      ].filter(Boolean).join(' ')}
      style={{ width: LAYOUT_NODE_W }}
    >
      <div className="wf-card__chrome">
        <button
          type="button"
          className="wf-card__grip"
          aria-label="拖动节点"
          onPointerDown={onDragStart}
        >
          <HolderOutlined />
        </button>
        <span className="wf-card__step">步骤 {index + 1}</span>
        <div className="wf-card__chrome-actions">
          <span
            className="wf-card__switch-wrap"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
          >
            <Switch
              size="small"
              checked={on}
              disabled={locked}
              onChange={(v) => onToggle(v)}
            />
          </span>
          {onRemove && (
            <button
              type="button"
              className="wf-card__icon-btn"
              aria-label="移除节点"
              onClick={(e) => {
                e.stopPropagation()
                onRemove()
              }}
            >
              <CloseOutlined />
            </button>
          )}
        </div>
      </div>

      <button type="button" className="wf-card__main" onClick={onSelect}>
        <div className="wf-card__head">
          <span className="wf-card__badge">{index + 1}</span>
          <div className="wf-card__titles">
            <span className="wf-card__title">{node.label || node.id}</span>
            <span className="wf-card__id">{node.id}</span>
          </div>
          <span className={`wf-card__role wf-card__role--${role}`}>{insight.roleLabel}</span>
        </div>

        <p className="wf-card__skill">{insight.skillLabel}</p>
        {insight.desc && <p className="wf-card__desc">{insight.desc}</p>}

        <div className="wf-card__stats">
          {insight.lines.slice(0, 3).map((line) => (
            <span key={line} className="wf-card__stat">{line}</span>
          ))}
        </div>

        {insight.bindingRulePills.length > 0 && (
          <div className="wf-card__rules">
            {insight.bindingRulePills.map((name) => (
              <span key={name} className="wf-card__rule" title={name}>{name}</span>
            ))}
          </div>
        )}

        <div className="wf-card__tags">
          {insight.pills.map((p) => (
            <span key={p} className="wf-card__tag">{p}</span>
          ))}
        </div>
      </button>

      <div className="wf-card__foot">
        <button type="button" className="wf-card__open" onClick={onSelect}>
          {cfgLabel}
          <RightOutlined />
        </button>
      </div>
    </div>
  )
}
