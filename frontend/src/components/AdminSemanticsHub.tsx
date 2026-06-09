import type { ComponentType, CSSProperties, ReactNode } from 'react'
import { CheckOutlined } from '@ant-design/icons'
import {
  ApiOutlined, DatabaseOutlined, NodeIndexOutlined, TableOutlined,
} from '@ant-design/icons'
import type { OntologyMapping } from '../api/client'
import { AdminMappingWorkbench } from './AdminMappingWorkbench'
import { AdminOntologyExplorer } from './AdminOntologyExplorer'

export const SEMANTICS_SUB_TABS = ['datasources', 'entities', 'mapping', 'graph'] as const
export type SemanticsSubTab = (typeof SEMANTICS_SUB_TABS)[number]

export const SEMANTICS_LEGACY_TAB: Record<string, SemanticsSubTab> = {
  mapping: 'mapping',
  datasources: 'datasources',
  ontology_explore: 'graph',
}

const FLOW: Array<{
  key: SemanticsSubTab
  label: string
  icon: ComponentType<{ className?: string }>
}> = [
  { key: 'datasources', label: '数据接入', icon: DatabaseOutlined },
  { key: 'entities', label: '实体与规则', icon: TableOutlined },
  { key: 'mapping', label: '字段映射', icon: ApiOutlined },
  { key: 'graph', label: '关系图谱', icon: NodeIndexOutlined },
]

export function semanticsProgressFromOntology(
  ontology: OntologyMapping,
): Record<SemanticsSubTab, boolean> {
  const mappingReady =
    (ontology.field_mappings?.length ?? 0) > 0
    || (ontology.db_mapping_configs?.some((c) => c.enabled) ?? false)
  return {
    datasources: (ontology.data_sources?.length ?? 0) > 0,
    entities: (ontology.object_types?.length ?? 0) > 0,
    mapping: mappingReady,
    graph: (ontology.relationships?.length ?? 0) > 0,
  }
}

type Props = {
  ontology: OntologyMapping
  activeSubTab: SemanticsSubTab
  onSubTabChange: (key: SemanticsSubTab) => void
  onSaved: () => void
  onNavigateToRuleEngine?: () => void
}

export function AdminSemanticsHub({
  ontology,
  activeSubTab,
  onSubTabChange,
  onSaved,
  onNavigateToRuleEngine,
}: Props) {
  const sub = SEMANTICS_SUB_TABS.includes(activeSubTab as SemanticsSubTab)
    ? activeSubTab
    : 'datasources'
  const done = semanticsProgressFromOntology(ontology)

  return (
    <div className="admin-semantics">
      <SemanticsFlowNav
        active={sub}
        done={done}
        onSelect={onSubTabChange}
      />
      <div className="admin-semantics__pane">
        {renderPane(sub, ontology, onSaved, onNavigateToRuleEngine)}
      </div>
    </div>
  )
}

function SemanticsFlowNav({
  active,
  done,
  onSelect,
}: {
  active: SemanticsSubTab
  done: Record<SemanticsSubTab, boolean>
  onSelect: (key: SemanticsSubTab) => void
}) {
  const activeIdx = FLOW.findIndex((s) => s.key === active)
  const nextKey = FLOW[activeIdx + 1]?.key
  const suggestNext = nextKey && done[active] && !done[nextKey]

  let progressIdx = 0
  for (let i = 0; i < FLOW.length; i += 1) {
    if (done[FLOW[i].key]) progressIdx = i
  }
  const progressPct = FLOW.length > 1 ? (progressIdx / (FLOW.length - 1)) * 100 : 0

  return (
    <nav
      className="semantics-flow"
      aria-label="数据语义配置"
      style={{ '--semantics-progress': `${progressPct}%` } as CSSProperties}
    >
      <div className="semantics-flow__track" aria-hidden>
        <div className="semantics-flow__fill" />
      </div>
      {FLOW.map((step) => {
        const isActive = step.key === active
        const isDone = done[step.key]
        const Icon = step.icon
        const suggest = suggestNext && step.key === nextKey

        return (
          <button
            key={step.key}
            type="button"
            className={[
              'semantics-flow__step',
              isActive ? 'semantics-flow__step--active' : '',
              isDone ? 'semantics-flow__step--done' : '',
              suggest ? 'semantics-flow__step--next' : '',
            ].filter(Boolean).join(' ')}
            onClick={() => onSelect(step.key)}
            aria-current={isActive ? 'step' : undefined}
          >
            <span className="semantics-flow__mark" aria-hidden>
              {isDone ? <CheckOutlined /> : <Icon />}
            </span>
            <span className="semantics-flow__label">{step.label}</span>
          </button>
        )
      })}
    </nav>
  )
}

/** 供流程编排内嵌：按语义子页渲染配置内容 */
export function AdminSemanticsPane({
  sub,
  ontology,
  onSaved,
  onNavigateToRuleEngine,
}: {
  sub: SemanticsSubTab
  ontology: OntologyMapping
  onSaved: () => void
  onNavigateToRuleEngine?: () => void
}): ReactNode {
  return renderPane(sub, ontology, onSaved, onNavigateToRuleEngine)
}

function renderPane(
  sub: SemanticsSubTab,
  ontology: OntologyMapping,
  onSaved: () => void,
  onNavigateToRuleEngine?: () => void,
): ReactNode {
  switch (sub) {
    case 'datasources':
      return <AdminMappingWorkbench data={ontology} view="datasources" onSaved={onSaved} />
    case 'entities':
      return (
        <AdminOntologyExplorer
          section="catalog"
          onNavigateToRuleEngine={onNavigateToRuleEngine}
        />
      )
    case 'mapping':
      return <AdminMappingWorkbench data={ontology} view="mapping" onSaved={onSaved} />
    case 'graph':
      return <AdminOntologyExplorer section="graph" />
    default:
      return null
  }
}
