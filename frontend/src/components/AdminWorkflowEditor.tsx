import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button, Space, Tooltip, message,
} from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'
import {
  BusinessCenter,
  LlmConfig,
  OntologyMapping,
  updateAdminWorkflow,
  WorkflowNode,
  type AdminRuleConfig,
} from '../api/client'
import { formatApiError } from '../api/errors'
import { getOntologyStats } from '../api/client'
import { ensureWorkflowNodes } from '../utils/workflowNodes'
import { cloneTemplate, type WorkflowNodeTemplate } from '../utils/workflowNodeCatalog'
import { defaultPosition, ensureNodePositions, positionsSignature, type NodePosition } from '../utils/workflowNodeLayout'
import type { AdminSkillRow } from './AdminSkillsPage'
import { AdminWorkflowFlowCanvas } from './AdminWorkflowFlowCanvas'
import { WorkflowNodeConfigModal } from './WorkflowNodeConfigModal'

const LOCKED_NODES = new Set(['import', 'mapping', 'ontology', 'detect'])

const NODE_CONFIG: Record<string, { tab: string; semSub?: string; label: string } | undefined> = {
  import: { tab: 'semantics', semSub: 'datasources', label: '接入' },
  mapping: { tab: 'semantics', semSub: 'mapping', label: '映射' },
  ontology: { tab: 'semantics', semSub: 'entities', label: '语义' },
  detect: { tab: 'rules', label: '规则' },
  ai_explain: { tab: 'llm', label: '模型' },
}

const WORKFLOW_HELP = (
  <>
    单击节点在画面中央打开统一配置窗；拖节点顶栏可自由摆放；画布空白处平移、滚轮缩放。
    工具栏「添加节点」可插入新步骤。保存后写入 Workflow。
  </>
)

type Props = {
  workflowId?: string
  workflow?: BusinessCenter['workflow']
  skills?: BusinessCenter['skills']
  center: BusinessCenter
  ontology: OntologyMapping | null
  rules: AdminRuleConfig[]
  llmConfig: LlmConfig | null
  onSaved?: () => void
  onNavigate: (tab: string, skillCode?: string, semSub?: string) => void
  onCreateRuleVersion: () => void
}

function nodeEnabled(n: WorkflowNode): boolean {
  return n.enabled !== false
}

function orderKey(nodes: WorkflowNode[]) {
  return nodes.map((n) => n.id).join('|')
}

function nodesSignature(nodes: WorkflowNode[]) {
  return nodes.map((n) => `${n.id}:${n.enabled !== false ? 1 : 0}`).join('|')
}

export function AdminWorkflowEditor({
  workflowId,
  workflow,
  skills,
  center,
  ontology,
  rules,
  llmConfig,
  onSaved,
  onNavigate,
  onCreateRuleVersion,
}: Props) {
  const sourceNodes = workflow?.nodes || []
  const [nodes, setNodes] = useState<WorkflowNode[]>(sourceNodes)
  const [saving, setSaving] = useState(false)
  const [configNodeId, setConfigNodeId] = useState<string | null>(null)
  const [ontologyStats, setOntologyStats] = useState<{
    entity_count: number
    published_rule_count: number
  } | null>(null)

  const skillRows = (skills || []) as AdminSkillRow[]

  useEffect(() => {
    getOntologyStats()
      .then((s) => setOntologyStats({
        entity_count: s.entity_count,
        published_rule_count: s.published_rule_count,
      }))
      .catch(() => setOntologyStats(null))
  }, [])

  useEffect(() => {
    const merged = ensureWorkflowNodes(sourceNodes)
    setNodes(ensureNodePositions(merged.map((n) => ({ ...n, enabled: n.enabled !== false }))))
  }, [workflow?.id, JSON.stringify(sourceNodes)])

  useEffect(() => {
    if (configNodeId && !nodes.some((n) => n.id === configNodeId)) {
      setConfigNodeId(null)
    }
  }, [nodes, configNodeId])

  const mergedSource = useMemo(
    () => ensureNodePositions(ensureWorkflowNodes(sourceNodes).map((n) => ({
      ...n,
      enabled: n.enabled !== false,
    }))),
    [sourceNodes],
  )
  const sourceOrder = useMemo(() => orderKey(mergedSource), [mergedSource])
  const currentOrder = useMemo(() => orderKey(nodes), [nodes])

  const dirty = useMemo(() => {
    if (sourceOrder !== currentOrder) return true
    if (nodesSignature(mergedSource) !== nodesSignature(nodes)) return true
    return positionsSignature(mergedSource) !== positionsSignature(nodes)
  }, [mergedSource, nodes, sourceOrder, currentOrder])

  const insightCtx = useMemo(() => ({
    ontology,
    ontologyStats,
    rules,
    llmConfig,
    skillName: (code?: string) => skills?.find((s) => s.code === code)?.name,
  }), [ontology, ontologyStats, rules, llmConfig, skills])

  const configNode = useMemo(
    () => nodes.find((n) => n.id === configNodeId) ?? null,
    [nodes, configNodeId],
  )

  const toggleNode = (id: string, enabled: boolean) => {
    setNodes((prev) => prev.map((n) => (n.id === id ? { ...n, enabled } : n)))
  }

  const moveNode = useCallback((id: string, position: NodePosition) => {
    setNodes((prev) => prev.map((n) => (n.id === id ? { ...n, position } : n)))
  }, [])

  const addNode = useCallback((template: WorkflowNodeTemplate, position?: NodePosition) => {
    setNodes((prev) => {
      if (prev.some((n) => n.id === template.id)) {
        message.info('该节点已在流程中')
        return prev
      }
      const node = {
        ...cloneTemplate(template),
        position: position || defaultPosition(prev.length),
      }
      message.success(`已添加「${template.label}」`)
      setConfigNodeId(template.id)
      return [...prev, node]
    })
  }, [])

  const removeNode = useCallback((id: string) => {
    if (LOCKED_NODES.has(id)) {
      message.warning('核心节点不可移除')
      return
    }
    setNodes((prev) => {
      const n = prev.find((x) => x.id === id)
      if (!n) return prev
      message.success(`已移除「${n.label || id}」`)
      if (configNodeId === id) setConfigNodeId(null)
      return prev.filter((x) => x.id !== id)
    })
  }, [configNodeId])

  const openInAssets = () => {
    if (!configNode) return
    const cfg = NODE_CONFIG[configNode.id]
    if (cfg) {
      onNavigate(cfg.tab, undefined, cfg.semSub)
      return
    }
    onNavigate('skills', configNode.skill_code || configNode.skill)
  }

  const handleSave = async () => {
    if (!workflowId) {
      message.warning('未找到 Workflow ID')
      return
    }
    setSaving(true)
    try {
      await updateAdminWorkflow(workflowId, {
        nodes: nodes.map((n) => ({
          id: n.id,
          enabled: nodeEnabled(n),
          position: n.position,
        })),
        node_order: nodes.map((n) => n.id),
      })
      message.success('流程配置已保存')
      onSaved?.()
    } catch (e) {
      message.error(formatApiError(e))
    } finally {
      setSaving(false)
    }
  }

  const enabledCount = nodes.filter((n) => nodeEnabled(n)).length
  const flowLabels = NODE_CONFIG as Record<string, { label: string } | undefined>
  const [toolbarHost, setToolbarHost] = useState<HTMLDivElement | null>(null)
  const toolbarHostRef = useCallback((el: HTMLDivElement | null) => {
    setToolbarHost(el)
  }, [])

  return (
    <div className="admin-wf-editor admin-wf-editor--fill admin-wf-editor--canvas">
      <div className="admin-wf-editor__topbar">
        <div className="admin-wf-editor__brand">
          <span className="admin-wf-editor__name">
            {workflow?.name || '收入核对 Workflow'}
          </span>
          <Tooltip title={WORKFLOW_HELP} placement="bottom">
            <QuestionCircleOutlined className="admin-wf-editor__help" />
          </Tooltip>
          <span className="admin-wf-editor__meta">
            v{workflow?.version ?? 1}
            <span className="admin-wf-editor__meta-sep">·</span>
            {workflow?.status === 'published' ? '已发布' : workflow?.status || 'published'}
            <span className="admin-wf-editor__meta-sep">·</span>
            {enabledCount}/{nodes.length} 节点
            {dirty && (
              <>
                <span className="admin-wf-editor__meta-sep">·</span>
                <span className="admin-wf-editor__meta-dirty">未保存</span>
              </>
            )}
          </span>
        </div>
        <div ref={toolbarHostRef} className="admin-wf-editor__toolbar-slot" />
        <Space size={6} className="admin-wf-editor__actions">
          {dirty && (
            <Button size="small" type="text" onClick={() => setNodes(mergedSource.map((n) => ({ ...n })))}>
              撤销
            </Button>
          )}
          <Button type="primary" size="small" loading={saving} disabled={!dirty} onClick={handleSave}>
            保存
          </Button>
        </Space>
      </div>

      <div className="admin-wf-editor__canvas-full">
        <AdminWorkflowFlowCanvas
          toolbarHost={toolbarHost}
          nodes={nodes}
          lockedIds={LOCKED_NODES}
          nodeConfig={flowLabels}
          insightCtx={insightCtx}
          selectedNodeId={configNodeId}
          onSelectNode={setConfigNodeId}
          onMoveNode={moveNode}
          onAddNode={addNode}
          onRemoveNode={removeNode}
          onToggle={toggleNode}
        />
      </div>

      <WorkflowNodeConfigModal
        open={!!configNodeId && !!configNode}
        node={configNode}
        ontology={ontology}
        center={center}
        rules={rules}
        skills={skillRows}
        onClose={() => setConfigNodeId(null)}
        onReload={() => onSaved?.()}
        onCreateRuleVersion={onCreateRuleVersion}
        onOpenInAssets={openInAssets}
      />
    </div>
  )
}
