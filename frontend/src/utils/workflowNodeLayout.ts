import type { WorkflowNode } from '../api/client'

export const LAYOUT_NODE_W = 220
export const LAYOUT_NODE_H = 168
export const LAYOUT_PAD = 48
export const LAYOUT_GAP_X = 88
export const LAYOUT_BASE_Y = 72

export type NodePosition = { x: number; y: number }

export function defaultPosition(index: number): NodePosition {
  return {
    x: LAYOUT_PAD + index * (LAYOUT_NODE_W + LAYOUT_GAP_X),
    y: LAYOUT_BASE_Y,
  }
}

export function getNodePosition(node: WorkflowNode, index: number): NodePosition {
  const p = node.position
  if (p && typeof p.x === 'number' && typeof p.y === 'number') {
    return { x: p.x, y: p.y }
  }
  return defaultPosition(index)
}

/** 为缺坐标的节点补默认布局（保留已有坐标） */
export function ensureNodePositions(nodes: WorkflowNode[]): WorkflowNode[] {
  return nodes.map((n, i) => {
    const p = getNodePosition(n, i)
    return { ...n, position: p }
  })
}

export function computeStageBounds(
  nodes: WorkflowNode[],
  extraPad = 120,
): { width: number; height: number } {
  if (!nodes.length) {
    return { width: 960, height: 360 }
  }
  let maxX = LAYOUT_PAD + LAYOUT_NODE_W
  let maxY = LAYOUT_BASE_Y + LAYOUT_NODE_H
  nodes.forEach((n, i) => {
    const p = getNodePosition(n, i)
    maxX = Math.max(maxX, p.x + LAYOUT_NODE_W)
    maxY = Math.max(maxY, p.y + LAYOUT_NODE_H)
  })
  return {
    width: Math.max(960, maxX + extraPad),
    height: Math.max(360, maxY + extraPad),
  }
}

export function nodeCenter(pos: NodePosition): { x: number; y: number } {
  return {
    x: pos.x + LAYOUT_NODE_W / 2,
    y: pos.y + LAYOUT_NODE_H * 0.46,
  }
}

export function positionsSignature(nodes: WorkflowNode[]): string {
  return nodes
    .map((n, i) => {
      const p = getNodePosition(n, i)
      return `${n.id}:${Math.round(p.x)},${Math.round(p.y)}`
    })
    .join('|')
}
