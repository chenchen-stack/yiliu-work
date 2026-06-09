import {
  useCallback, useEffect, useMemo, useRef, useState,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { createPortal } from 'react-dom'
import { Button, Popover, Tooltip } from 'antd'
import {
  PlusOutlined, ZoomInOutlined, ZoomOutOutlined, CompressOutlined,
} from '@ant-design/icons'
import type { WorkflowNode } from '../api/client'
import {
  listAddableNodeTemplates,
  templateForNodeId,
  type WorkflowNodeTemplate,
} from '../utils/workflowNodeCatalog'
import {
  computeStageBounds,
  getNodePosition,
  LAYOUT_NODE_H,
  LAYOUT_NODE_W,
  LAYOUT_PAD,
  type NodePosition,
  nodeCenter,
} from '../utils/workflowNodeLayout'
import { buildWorkflowNodeInsight } from '../utils/workflowNodeInsights'
import type { WorkflowNodeInsight } from '../utils/workflowNodeInsights'
import { WorkflowFlowNodeCard } from './WorkflowFlowNodeCard'

export const FLOW_NODE_W = LAYOUT_NODE_W
export const FLOW_NODE_GAP = 88

type OntologyStats = { entity_count: number; published_rule_count: number } | null

type InsightCtx = Parameters<typeof buildWorkflowNodeInsight>[2]

type Props = {
  toolbarHost?: HTMLDivElement | null
  nodes: WorkflowNode[]
  lockedIds: Set<string>
  nodeConfig: Record<string, { label: string } | undefined>
  insightCtx: InsightCtx
  onMoveNode: (id: string, position: NodePosition) => void
  onAddNode: (template: WorkflowNodeTemplate, position?: NodePosition) => void
  onRemoveNode: (id: string) => void
  selectedNodeId: string | null
  onSelectNode: (nodeId: string) => void
  onToggle: (id: string, enabled: boolean) => void
}

function enabled(n: WorkflowNode) {
  return n.enabled !== false
}

function stagePoint(clientX: number, clientY: number, viewport: HTMLDivElement, scale: number): NodePosition {
  const rect = viewport.getBoundingClientRect()
  const margin = 24
  return {
    x: (clientX - rect.left + viewport.scrollLeft - margin) / scale - LAYOUT_NODE_W / 2,
    y: (clientY - rect.top + viewport.scrollTop - margin) / scale - 40,
  }
}

export function AdminWorkflowFlowCanvas({
  toolbarHost,
  nodes,
  lockedIds,
  nodeConfig,
  insightCtx,
  onMoveNode,
  onAddNode,
  onRemoveNode,
  selectedNodeId,
  onSelectNode,
  onToggle,
}: Props) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)
  const [panning, setPanning] = useState(false)
  const panStart = useRef({ x: 0, y: 0, sl: 0, st: 0 })
  const [dragId, setDragId] = useState<string | null>(null)
  const dragOrigin = useRef<NodePosition>({ x: 0, y: 0 })
  const dragPointer = useRef({ x: 0, y: 0 })
  const [livePos, setLivePos] = useState<NodePosition | null>(null)
  const [paletteDragId, setPaletteDragId] = useState<string | null>(null)
  const [paletteGhost, setPaletteGhost] = useState<NodePosition | null>(null)
  const [paletteOpen, setPaletteOpen] = useState(false)

  const existingIds = useMemo(() => new Set(nodes.map((n) => n.id)), [nodes])
  const addable = useMemo(() => listAddableNodeTemplates(existingIds), [existingIds])

  const { width: stageW, height: stageH } = useMemo(() => computeStageBounds(nodes), [nodes])

  const displayPos = useCallback(
    (n: WorkflowNode, i: number): NodePosition => {
      if (dragId === n.id && livePos) return livePos
      return getNodePosition(n, i)
    },
    [dragId, livePos, nodes],
  )

  const edges = useMemo(() => {
    return nodes.slice(1).map((node, i) => {
      const prev = nodes[i]
      const p0 = displayPos(prev, i)
      const p1 = displayPos(node, i + 1)
      const c0 = nodeCenter(p0)
      const c1 = nodeCenter(p1)
      const on = enabled(prev) && enabled(node)
      return {
        id: `${prev.id}-${node.id}`,
        x0: c0.x + LAYOUT_NODE_W * 0.38,
        y0: c0.y,
        x1: c1.x - LAYOUT_NODE_W * 0.38,
        y1: c1.y,
        on,
      }
    })
  }, [nodes, displayPos])

  const edgePath = (x0: number, y0: number, x1: number, y1: number) => {
    const dx = Math.max(48, Math.abs(x1 - x0) * 0.35)
    return `M ${x0} ${y0} C ${x0 + dx} ${y0}, ${x1 - dx} ${y1}, ${x1} ${y1}`
  }

  const insights = useMemo(() => {
    const map = new Map<string, WorkflowNodeInsight>()
    nodes.forEach((n, i) => {
      map.set(n.id, buildWorkflowNodeInsight(n, i, {
        ...insightCtx,
        configLabel: nodeConfig[n.id]?.label,
      }))
    })
    return map
  }, [nodes, insightCtx, nodeConfig])

  const onViewportPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || dragId || paletteDragId) return
    const t = e.target as HTMLElement
    if (t.closest('.wf-card') || t.closest('.admin-wf-flow__toolbar')) return
    const vp = viewportRef.current
    if (!vp) return
    setPanning(true)
    panStart.current = { x: e.clientX, y: e.clientY, sl: vp.scrollLeft, st: vp.scrollTop }
    vp.setPointerCapture(e.pointerId)
  }

  const onViewportPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const vp = viewportRef.current
    if (!vp) return
    if (panning) {
      vp.scrollLeft = panStart.current.sl - (e.clientX - panStart.current.x)
      vp.scrollTop = panStart.current.st - (e.clientY - panStart.current.y)
      return
    }
    const scaleDelta = 1 / scale
    if (dragId) {
      const dx = (e.clientX - dragPointer.current.x) * scaleDelta
      const dy = (e.clientY - dragPointer.current.y) * scaleDelta
      setLivePos({
        x: Math.max(LAYOUT_PAD, dragOrigin.current.x + dx),
        y: Math.max(24, dragOrigin.current.y + dy),
      })
    }
    if (paletteDragId) {
      setPaletteGhost(stagePoint(e.clientX, e.clientY, vp, scale))
    }
  }

  const endPan = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (panning) {
      setPanning(false)
      viewportRef.current?.releasePointerCapture(e.pointerId)
    }
  }

  const finishNodeDrag = useCallback(() => {
    if (dragId && livePos) {
      onMoveNode(dragId, livePos)
    }
    setDragId(null)
    setLivePos(null)
  }, [dragId, livePos, onMoveNode])

  const finishPaletteDrag = useCallback(() => {
    if (paletteDragId) {
      const tpl = templateForNodeId(paletteDragId)
      if (tpl) {
        const pos = paletteGhost || {
          x: LAYOUT_PAD + nodes.length * (LAYOUT_NODE_W + 88),
          y: 72,
        }
        onAddNode(tpl, { x: Math.max(LAYOUT_PAD, pos.x), y: Math.max(24, pos.y) })
      }
    }
    setPaletteDragId(null)
    setPaletteGhost(null)
  }, [paletteDragId, paletteGhost, onAddNode, nodes.length])

  useEffect(() => {
    if (!dragId) return
    const onUp = () => finishNodeDrag()
    window.addEventListener('pointerup', onUp)
    return () => window.removeEventListener('pointerup', onUp)
  }, [dragId, finishNodeDrag])

  useEffect(() => {
    if (!paletteDragId) return
    const onUp = () => finishPaletteDrag()
    window.addEventListener('pointerup', onUp)
    return () => window.removeEventListener('pointerup', onUp)
  }, [paletteDragId, finishPaletteDrag])

  const startNodeDrag = (id: string, index: number) => (e: ReactPointerEvent) => {
    if (e.button !== 0) return
    e.preventDefault()
    e.stopPropagation()
    const p = getNodePosition(nodes.find((n) => n.id === id) || nodes[index], index)
    dragOrigin.current = { ...p }
    dragPointer.current = { x: e.clientX, y: e.clientY }
    setLivePos({ ...p })
    setDragId(id)
  }

  const startPaletteDrag = (templateId: string) => (e: ReactPointerEvent) => {
    if (e.button !== 0) return
    e.preventDefault()
    setPaletteDragId(templateId)
    const vp = viewportRef.current
    if (vp) setPaletteGhost(stagePoint(e.clientX, e.clientY, vp, scale))
  }

  const zoom = useCallback((delta: number) => {
    setScale((s) => Math.min(1.35, Math.max(0.65, +(s + delta).toFixed(2))))
  }, [])

  useEffect(() => {
    const vp = viewportRef.current
    if (!vp) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const step = e.deltaMode === 1 ? 0.12 : 0.06
      zoom(e.deltaY > 0 ? -step : step)
    }
    vp.addEventListener('wheel', onWheel, { passive: false })
    return () => vp.removeEventListener('wheel', onWheel)
  }, [zoom])

  const toolbar = (
    <div className="admin-wf-flow__toolbar admin-wf-flow__toolbar--inline">
      <Popover
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        trigger="click"
        placement="bottomLeft"
        overlayClassName="admin-wf-flow__palette-pop"
        content={(
          <div className="admin-wf-flow__palette-pop-inner">
            {addable.length === 0 ? (
              <p className="admin-wf-flow__palette-empty">流程已包含全部可用节点</p>
            ) : (
              addable.map((tpl) => (
                <div
                  key={tpl.id}
                  className={`admin-wf-flow__palette-item admin-wf-flow__palette-item--${tpl.role}`}
                >
                  <button
                    type="button"
                    className="admin-wf-flow__palette-drag"
                    aria-label={`拖动 ${tpl.label}`}
                    onPointerDown={startPaletteDrag(tpl.id)}
                  >
                    ⋮⋮
                  </button>
                  <button
                    type="button"
                    className="admin-wf-flow__palette-add"
                    onClick={() => {
                      onAddNode(tpl)
                      setPaletteOpen(false)
                    }}
                  >
                    <span className="admin-wf-flow__palette-dot" />
                    <span className="admin-wf-flow__palette-label">{tpl.label}</span>
                    <span className="admin-wf-flow__palette-code">{tpl.id}</span>
                    {tpl.description && (
                      <span className="admin-wf-flow__palette-desc">{tpl.description}</span>
                    )}
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      >
        <Button type="default" size="small" icon={<PlusOutlined />}>
          添加节点
        </Button>
      </Popover>
        <Tooltip title="点击节点配置 · 拖顶栏移动 · 空白平移 · 滚轮缩放">
        <span className="admin-wf-flow__hint-icon" aria-label="操作提示">?</span>
      </Tooltip>
      <div className="admin-wf-flow__zoom">
        <button type="button" className="admin-wf-flow__zoom-btn" onClick={() => zoom(-0.1)} aria-label="缩小">
          <ZoomOutOutlined />
        </button>
        <span className="admin-wf-flow__zoom-val">{Math.round(scale * 100)}%</span>
        <button type="button" className="admin-wf-flow__zoom-btn" onClick={() => zoom(0.1)} aria-label="放大">
          <ZoomInOutlined />
        </button>
        <button type="button" className="admin-wf-flow__zoom-btn" onClick={() => setScale(1)} aria-label="重置">
          <CompressOutlined />
        </button>
      </div>
    </div>
  )

  return (
    <div className="admin-wf-flow">
      {toolbarHost ? createPortal(toolbar, toolbarHost) : toolbar}

      <div
        ref={viewportRef}
        className={`admin-wf-flow__viewport admin-wf-flow__viewport--full${panning ? ' admin-wf-flow__viewport--panning' : ''}`}
          onPointerDown={onViewportPointerDown}
          onPointerMove={onViewportPointerMove}
          onPointerUp={endPan}
          onPointerLeave={endPan}
        >
          <div
            className="admin-wf-flow__stage-wrap"
            style={{ width: stageW * scale, height: stageH * scale }}
          >
            <div
              className="admin-wf-flow__stage"
              style={{
                width: stageW,
                height: stageH,
                transform: `scale(${scale})`,
                transformOrigin: '0 0',
              }}
            >
              <svg className="admin-wf-flow__edges" width={stageW} height={stageH} aria-hidden>
                <defs>
                  <marker id="wf-arrow-on" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
                    <path d="M0,0 L7,3.5 L0,7 Z" fill="#cbd5e1" />
                  </marker>
                  <marker id="wf-arrow-off" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
                    <path d="M0,0 L7,3.5 L0,7 Z" fill="#e2e8f0" />
                  </marker>
                </defs>
                {edges.map((e) => (
                  <path
                    key={e.id}
                    d={edgePath(e.x0, e.y0, e.x1, e.y1)}
                    className={e.on ? 'admin-wf-flow__edge admin-wf-flow__edge--on' : 'admin-wf-flow__edge'}
                    markerEnd={e.on ? 'url(#wf-arrow-on)' : 'url(#wf-arrow-off)'}
                  />
                ))}
              </svg>

              {paletteGhost && paletteDragId && (
                <div
                  className="admin-wf-flow__ghost"
                  style={{
                    left: paletteGhost.x,
                    top: paletteGhost.y,
                    width: LAYOUT_NODE_W,
                    height: LAYOUT_NODE_H,
                  }}
                >
                  {templateForNodeId(paletteDragId)?.label}
                </div>
              )}

              <div className="admin-wf-flow__nodes" style={{ width: stageW, height: stageH }}>
                {nodes.map((n, i) => {
                  const pos = displayPos(n, i)
                  const insight = insights.get(n.id)!
                  return (
                    <div
                      key={n.id}
                      className="admin-wf-flow-node-wrap"
                      style={{ left: pos.x, top: pos.y }}
                    >
                      <WorkflowFlowNodeCard
                        node={n}
                        index={i}
                        insight={insight}
                        locked={lockedIds.has(n.id)}
                        selected={selectedNodeId === n.id}
                        dragging={dragId === n.id}
                        configLabel={nodeConfig[n.id]?.label}
                        onToggle={(v) => onToggle(n.id, v)}
                        onSelect={() => onSelectNode(n.id)}
                        onDragStart={startNodeDrag(n.id, i)}
                        onRemove={!lockedIds.has(n.id) ? () => onRemoveNode(n.id) : undefined}
                      />
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
      </div>
    </div>
  )
}
