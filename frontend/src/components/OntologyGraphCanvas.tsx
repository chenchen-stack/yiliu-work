import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Radio, Space, Tag, Typography } from 'antd'
import { ZoomInOutlined, ZoomOutOutlined, DragOutlined } from '@ant-design/icons'
import { DatasourceBrandIcon, ontologyLayerVisualKey } from '../utils/datasourceBranding'
import type { DatasourceCatalog } from '../utils/datasourceCatalog'

export type GraphNode = {
  id: string
  label: string
  table_name: string
  datasource_code: string
  description?: string
  column_count?: number
}

export type GraphEdge = {
  id: string
  source: string
  target: string
  from_column: string
  to_column: string
  relation_type?: string
  label?: string
  description?: string
}

export type GraphLayer = { key: string; title: string; color: string }

const LAYER_X: Record<string, number> = {
  fanruan_pg: 420,
  sap_pg: 120,
  dms_pg: 720,
  knowledge: 420,
}
const LAYER_DEFAULT_X = 300
const NODE_W = 200
const NODE_H = 48
/** 内容区四周留白，可继续拖入空白区域（近似无限画布） */
const CANVAS_PAD = 960
const MIN_STAGE_W = 3200
const MIN_STAGE_H = 2400

type Props = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  layers: GraphLayer[]
  height?: number
  onNodeClick?: (node: GraphNode) => void
}

type LayoutNode = GraphNode & { x: number; y: number; color: string }

/** 避免 from 已含箭头时再次拼接 to，造成「A -> B → B」重复 */
function formatEdgeLabel(edge: GraphEdge): string {
  const from = (edge.from_column || '').trim()
  const to = (edge.to_column || '').trim()
  if (edge.label?.trim() && !from && !to) return edge.label.trim()
  if (!from && to) return to
  if (!to || from === to) return from
  if (/[→]|->|—/.test(from) && (!to || from.includes(to))) return from
  if (from.includes(`→ ${to}`) || from.includes(`-> ${to}`)) return from
  return `${from} → ${to}`
}

function layerColor(code: string, layers: GraphLayer[]): string {
  return layers.find((l) => l.key === code)?.color || '#64748b'
}

function computeLayout(nodes: GraphNode[], layers: GraphLayer[]): LayoutNode[] {
  const groups: Record<string, GraphNode[]> = {}
  for (const n of nodes) {
    const k = n.datasource_code || 'other'
    groups[k] = groups[k] || []
    groups[k].push(n)
  }
  const ordered = ['fanruan_pg', 'sap_pg', 'dms_pg', 'knowledge', ...Object.keys(groups)]
  const seen = new Set<string>()
  const layout: LayoutNode[] = []
  let globalY = 80
  for (const ds of ordered) {
    if (seen.has(ds) || !groups[ds]?.length) continue
    seen.add(ds)
    const list = groups[ds]
    const x = LAYER_X[ds] ?? LAYER_DEFAULT_X
    list.forEach((n, i) => {
      layout.push({
        ...n,
        x,
        y: globalY + i * 88,
        color: layerColor(ds, layers),
      })
    })
    globalY += list.length * 88 + 40
  }
  return layout
}

type DragMode = 'pan' | 'node' | null

export function OntologyGraphCanvas({
  nodes,
  edges,
  layers,
  height = 520,
  onNodeClick,
}: Props) {
  const [hoverEdge, setHoverEdge] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [scale, setScale] = useState(1)
  const [nodeOffsets, setNodeOffsets] = useState<Record<string, { dx: number; dy: number }>>({})
  const dragRef = useRef<{
    mode: DragMode
    startX: number
    startY: number
    panX: number
    panY: number
    nodeId?: string
    nodeDx?: number
    nodeDy?: number
    moved: boolean
  } | null>(null)
  const viewportRef = useRef<HTMLDivElement>(null)

  const layoutNodes = useMemo(() => computeLayout(nodes, layers), [nodes, layers])

  const posMap = useMemo(() => {
    const m = new Map<string, LayoutNode & { dx: number; dy: number }>()
    layoutNodes.forEach((n) => {
      const off = nodeOffsets[n.id] || { dx: 0, dy: 0 }
      m.set(n.id, { ...n, dx: off.dx, dy: off.dy })
    })
    return m
  }, [layoutNodes, nodeOffsets])

  const canvasLayout = useMemo(() => {
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity
    for (const n of layoutNodes) {
      const off = nodeOffsets[n.id] || { dx: 0, dy: 0 }
      const tx = n.x - 100 + off.dx
      const ty = n.y + off.dy
      minX = Math.min(minX, tx)
      minY = Math.min(minY, ty)
      maxX = Math.max(maxX, tx + NODE_W)
      maxY = Math.max(maxY, ty + NODE_H)
    }
    if (!layoutNodes.length) {
      minX = 0
      minY = 0
      maxX = 920
      maxY = 520
    }
    const contentW = maxX - minX
    const contentH = maxY - minY
    const stageW = Math.max(MIN_STAGE_W, contentW + CANVAS_PAD * 2)
    const stageH = Math.max(MIN_STAGE_H, contentH + CANVAS_PAD * 2)
    const offsetX = CANVAS_PAD - minX
    const offsetY = CANVAS_PAD - minY
    return {
      stageW,
      stageH,
      offsetX,
      offsetY,
      contentW,
      contentH,
      centerX: offsetX + contentW / 2,
      centerY: offsetY + contentH / 2,
    }
  }, [layoutNodes, nodeOffsets])

  const centerView = useCallback((forScale?: number) => {
    const vp = viewportRef.current
    if (!vp) return
    const s = forScale ?? scale
    const vw = vp.clientWidth
    const vh = vp.clientHeight
    setPan({
      x: vw / 2 - canvasLayout.centerX * s,
      y: vh / 2 - canvasLayout.centerY * s,
    })
  }, [canvasLayout.centerX, canvasLayout.centerY, scale])

  const nodesKey = useMemo(() => nodes.map((n) => n.id).join('|'), [nodes])

  useEffect(() => {
    const t = window.setTimeout(() => centerView(1), 0)
    return () => window.clearTimeout(t)
    // 仅在切换图谱数据集时居中，避免缩放/拖拽后被拉回
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodesKey])

  /** 同一对节点间多条边时错开标签纵坐标，防止文字叠影 */
  const edgeLabelIndex = useMemo(() => {
    const groups = new Map<string, GraphEdge[]>()
    for (const e of edges) {
      const key = `${e.source}|${e.target}`
      const list = groups.get(key) || []
      list.push(e)
      groups.set(key, list)
    }
    const indexById = new Map<string, { index: number; total: number }>()
    groups.forEach((list) => {
      list.forEach((e, i) => indexById.set(e.id, { index: i, total: list.length }))
    })
    return indexById
  }, [edges])

  const onViewportPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return
    dragRef.current = {
      mode: 'pan',
      startX: e.clientX,
      startY: e.clientY,
      panX: pan.x,
      panY: pan.y,
      moved: false,
    }
    viewportRef.current?.setPointerCapture(e.pointerId)
    e.preventDefault()
  }

  const onViewportPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current
    if (!d) return
    const dx = e.clientX - d.startX
    const dy = e.clientY - d.startY
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true

    if (d.mode === 'pan') {
      setPan({ x: d.panX + dx, y: d.panY + dy })
    } else if (d.mode === 'node' && d.nodeId) {
      setNodeOffsets((prev) => ({
        ...prev,
        [d.nodeId!]: {
          dx: (d.nodeDx ?? 0) + dx,
          dy: (d.nodeDy ?? 0) + dy,
        },
      }))
    }
  }

  const onViewportPointerUp = (e: React.PointerEvent) => {
    const d = dragRef.current
    if (d?.mode === 'node' && !d.moved && d.nodeId) {
      const n = layoutNodes.find((x) => x.id === d.nodeId)
      if (n) {
        setSelectedId(n.id)
        onNodeClick?.(n)
      }
    }
    try {
      viewportRef.current?.releasePointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
    dragRef.current = null
  }

  const onNodePointerDown = (e: React.PointerEvent, nodeId: string) => {
    e.stopPropagation()
    const off = nodeOffsets[nodeId] || { dx: 0, dy: 0 }
    dragRef.current = {
      mode: 'node',
      startX: e.clientX,
      startY: e.clientY,
      panX: pan.x,
      panY: pan.y,
      nodeId,
      nodeDx: off.dx,
      nodeDy: off.dy,
      moved: false,
    }
    viewportRef.current?.setPointerCapture(e.pointerId)
    e.preventDefault()
  }

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? -0.08 : 0.08
    setScale((s) => Math.min(2, Math.max(0.4, s + delta)))
  }

  const resetView = () => {
    setScale(1)
    setNodeOffsets({})
    window.setTimeout(() => centerView(1), 50)
  }

  return (
    <div className="ontology-graph">
      <div className="ontology-graph__legend">
        {layers.map((l) => {
          const visualKey = ontologyLayerVisualKey(l.key)
          const showBrand = visualKey !== 'generic'
          return (
            <Tag
              key={l.key}
              color={l.color}
              style={{ borderColor: l.color, color: l.color, background: '#fff', display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              {showBrand && (
                <DatasourceBrandIcon
                  catalog={visualKey as DatasourceCatalog | 'knowledge'}
                  size={16}
                  showEngine={visualKey === 'sap' || visualKey === 'dms'}
                />
              )}
              {l.title}
            </Tag>
          )
        })}
        <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
          <DragOutlined /> 拖空白处平移画布 · 拖节点可挪动 · 滚轮缩放 · 点击节点查看字段
        </Typography.Text>
        <Space style={{ marginLeft: 'auto' }}>
          <Button size="small" icon={<ZoomOutOutlined />} onClick={() => setScale((s) => Math.max(0.4, s - 0.1))} />
          <Button size="small" icon={<ZoomInOutlined />} onClick={() => setScale((s) => Math.min(2, s + 0.1))} />
          <Button size="small" onClick={resetView}>重置视图</Button>
        </Space>
      </div>
      <div
        ref={viewportRef}
        className="ontology-graph__viewport ontology-graph__viewport--pan"
        style={{ height }}
        onPointerDown={onViewportPointerDown}
        onPointerMove={onViewportPointerMove}
        onPointerUp={onViewportPointerUp}
        onPointerLeave={onViewportPointerUp}
        onWheel={onWheel}
      >
        <div
          className="ontology-graph__stage"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`,
            width: canvasLayout.stageW,
            height: canvasLayout.stageH,
          }}
        >
          <svg className="ontology-graph__svg" width={canvasLayout.stageW} height={canvasLayout.stageH}>
            <defs>
              <pattern
                id="ontology-grid"
                width={24}
                height={24}
                patternUnits="userSpaceOnUse"
              >
                <circle cx={1} cy={1} r={0.8} fill="#e2e8f0" />
              </pattern>
              <marker id="ontology-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 Z" fill="#94a3b8" />
              </marker>
            </defs>
            <rect
              width={canvasLayout.stageW}
              height={canvasLayout.stageH}
              fill="url(#ontology-grid)"
            />
            <g transform={`translate(${canvasLayout.offsetX}, ${canvasLayout.offsetY})`}>
            {edges.map((e) => {
              const from = posMap.get(e.source)
              const to = posMap.get(e.target)
              if (!from || !to) return null
              const x1 = from.x + from.dx + 100
              const y1 = from.y + from.dy + 24
              const x2 = to.x + to.dx
              const y2 = to.y + to.dy + 24
              const mx = (x1 + x2) / 2
              const active = hoverEdge === e.id || selectedId === e.source || selectedId === e.target
              const labelMeta = edgeLabelIndex.get(e.id)
              const labelIdx = labelMeta?.index ?? 0
              const labelTotal = labelMeta?.total ?? 1
              const labelY = (y1 + y2) / 2 - 6 + (labelIdx - (labelTotal - 1) / 2) * 15
              const labelText = formatEdgeLabel(e)
              const labelW = Math.min(220, Math.max(72, labelText.length * 6.5))
              return (
                <g
                  key={e.id}
                  onMouseEnter={() => setHoverEdge(e.id)}
                  onMouseLeave={() => setHoverEdge(null)}
                  style={{ pointerEvents: 'stroke' }}
                >
                  <path
                    d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                    fill="none"
                    stroke={active ? '#f97316' : '#cbd5e1'}
                    strokeWidth={active ? 2.5 : 1.5}
                    markerEnd="url(#ontology-arrow)"
                  />
                  <g className="ontology-graph__edge-label-wrap" pointerEvents="none">
                    <rect
                      x={mx - labelW / 2}
                      y={labelY - 11}
                      width={labelW}
                      height={14}
                      rx={3}
                      fill="#fff"
                      fillOpacity={active ? 1 : 0.92}
                      stroke={active ? '#fed7aa' : '#e2e8f0'}
                      strokeWidth={1}
                    />
                    <text
                      x={mx}
                      y={labelY}
                      textAnchor="middle"
                      className="ontology-graph__edge-label"
                      fill={active ? '#ea580c' : '#64748b'}
                    >
                      {labelText}
                    </text>
                  </g>
                </g>
              )
            })}

            {layoutNodes.map((n) => {
              const off = nodeOffsets[n.id] || { dx: 0, dy: 0 }
              const selected = selectedId === n.id
              const tx = n.x - 100 + off.dx
              const ty = n.y + off.dy
              return (
                <g
                  key={n.id}
                  transform={`translate(${tx}, ${ty})`}
                  className="ontology-graph__node"
                  onPointerDown={(ev) => onNodePointerDown(ev, n.id)}
                  style={{ cursor: 'grab' }}
                >
                  <rect
                    width={NODE_W}
                    height={NODE_H}
                    rx={10}
                    fill="#fff"
                    stroke={selected ? n.color : '#e2e8f0'}
                    strokeWidth={selected ? 2.5 : 1.5}
                  />
                  <rect width={6} height={NODE_H} rx={3} fill={n.color} />
                  <text x={14} y={20} className="ontology-graph__node-title" fill="#0f172a">
                    {n.label.length > 14 ? `${n.label.slice(0, 14)}…` : n.label}
                  </text>
                  <text x={14} y={36} className="ontology-graph__node-sub" fill="#64748b">
                    {n.column_count ?? 0} 字段 · {n.table_name.slice(0, 12)}
                  </text>
                </g>
              )
            })}
            </g>
          </svg>
        </div>
      </div>
    </div>
  )
}

type GraphViewProps = {
  fullNodes: GraphNode[]
  fullEdges: GraphEdge[]
  layers: GraphLayer[]
  onNodeClick?: (node: GraphNode) => void
}

export function OntologyGraphPanel({ fullNodes, fullEdges, layers, onNodeClick }: GraphViewProps) {
  const [view, setView] = useState<'core' | 'full'>('core')

  const coreKeys = new Set([
    'sap_pg.public.sap_settlement_line',
    'dms_pg.public.dms_revenue_ledger',
    'fanruan_pg.public.fanruan_reconciliation',
    'dms_pg.public.dms_settlement_order',
    'sap_pg.public.sap_settlement',
  ])

  const nodes = view === 'core' ? fullNodes.filter((n) => coreKeys.has(n.id)) : fullNodes
  const nodeIds = new Set(nodes.map((n) => n.id))
  const edges = fullEdges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Radio.Group value={view} onChange={(e) => setView(e.target.value)}>
          <Radio.Button value="core">主核对图谱</Radio.Button>
          <Radio.Button value="full">全量实体图谱</Radio.Button>
        </Radio.Group>
      </div>
      <OntologyGraphCanvas
        nodes={nodes}
        edges={edges}
        layers={layers}
        onNodeClick={onNodeClick}
      />
    </div>
  )
}
