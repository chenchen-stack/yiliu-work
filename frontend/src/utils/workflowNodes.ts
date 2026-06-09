import type { WorkflowNode } from '../api/client'
import { defaultPosition } from './workflowNodeLayout'

/** 与后端 WORKFLOW_NODES 一致的标准执行顺序 */
export const CANONICAL_WORKFLOW_ORDER = [
  'import',
  'ontology',
  'mapping',
  'detect',
  'ai_explain',
  'review',
  'verify',
  'report',
] as const

const DEFAULT_ONTOLOGY_NODE: WorkflowNode = {
  id: 'ontology',
  skill: 'ontology_context',
  skill_code: 'ontology_context',
  label: '实体与规则',
  enabled: true,
}

export function reorderWorkflowNodes(nodes: WorkflowNode[]): WorkflowNode[] {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const ordered: WorkflowNode[] = []
  for (const id of CANONICAL_WORKFLOW_ORDER) {
    const hit = byId.get(id)
    if (hit) {
      ordered.push(hit)
      byId.delete(id)
    }
  }
  for (const n of nodes) {
    if (byId.has(n.id)) ordered.push(byId.get(n.id)!)
  }
  return ordered
}

function hadLegacyCoreOrder(nodes: WorkflowNode[]): boolean {
  const ids = nodes.map((n) => n.id)
  const mi = ids.indexOf('mapping')
  const oi = ids.indexOf('ontology')
  return mi >= 0 && oi >= 0 && mi < oi
}

/** 旧画布上 mapping 在 ontology 左侧时，按新标准重排核心四步的横向坐标 */
function alignCoreChainPositions(nodes: WorkflowNode[]): WorkflowNode[] {
  return nodes.map((n, i) => {
    const coreIdx = CANONICAL_WORKFLOW_ORDER.indexOf(
      n.id as (typeof CANONICAL_WORKFLOW_ORDER)[number],
    )
    if (coreIdx >= 0 && coreIdx <= 3) {
      return { ...n, position: defaultPosition(coreIdx) }
    }
    return { ...n, position: n.position ?? defaultPosition(i) }
  })
}

/** 与后端 ensure_workflow_nodes 一致：补全 ontology 并规范顺序（接入 → 实体 → 映射 → 识别） */
export function ensureWorkflowNodes(nodes: WorkflowNode[]): WorkflowNode[] {
  if (!nodes.length) return [DEFAULT_ONTOLOGY_NODE]
  const legacy = hadLegacyCoreOrder(nodes)
  const byId = new Map(nodes.map((n) => [n.id, { ...n }]))
  if (!byId.has('ontology')) {
    byId.set('ontology', { ...DEFAULT_ONTOLOGY_NODE })
  }
  const merged = Array.from(byId.values())
  const ordered = reorderWorkflowNodes(merged)
  return legacy ? alignCoreChainPositions(ordered) : ordered
}
