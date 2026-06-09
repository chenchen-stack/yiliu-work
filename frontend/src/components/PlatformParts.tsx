import { Tag } from 'antd'

export function LayerBlock({ level, title, children, color }: {
  level: string; title: string; children: React.ReactNode; color?: string
}) {
  return (
    <div className={`layer-card layer-${level}`}>
      <div className="layer-head" style={color ? { background: color } : undefined}>
        {title}
      </div>
      <div className="layer-body">{children}</div>
    </div>
  )
}

export function GovTags() {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {['RBAC权限治理', '发布/版本', '审计追溯', '模型/接口监控', '安全管控'].map((t) => (
        <Tag key={t} color="default">{t}</Tag>
      ))}
    </div>
  )
}
