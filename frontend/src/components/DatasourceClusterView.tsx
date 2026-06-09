import { useMemo, useState } from 'react'
import { Popconfirm, Tooltip } from 'antd'
import { DeleteOutlined, RightOutlined, TableOutlined } from '@ant-design/icons'
import type { AdminDataSource } from '../api/client'
import {
  buildDatasourceClusters,
  DatasourceBrandIcon,
  type DatasourceCluster,
} from '../utils/datasourceBranding'

type Props = {
  datasources: AdminDataSource[]
  onPreview: (ds: AdminDataSource) => void
  onDelete: (id: string) => void
}

export function DatasourceClusterView({ datasources, onPreview, onDelete }: Props) {
  const clusters = useMemo(() => buildDatasourceClusters(datasources), [datasources])

  return (
    <div className="ds-db-grid">
      {clusters.map((cluster) => (
        <DatasourceDbCard
          key={cluster.id}
          cluster={cluster}
          onPreview={onPreview}
          onDelete={onDelete}
        />
      ))}
    </div>
  )
}

function DatasourceDbCard({
  cluster,
  onPreview,
  onDelete,
}: {
  cluster: DatasourceCluster
  onPreview: (ds: AdminDataSource) => void
  onDelete: (id: string) => void
}) {
  const [open, setOpen] = useState(cluster.tableCount <= 4)

  return (
    <article className={`ds-db-card ds-db-card--${cluster.catalog}`}>
      <div className="ds-db-card__top">
        <DatasourceBrandIcon catalog={cluster.catalog} size={28} />
        <div className="ds-db-card__main">
          <div className="ds-db-card__title-line">
            <span className="ds-db-card__title">{cluster.dbTitle}</span>
          </div>
          <p className="ds-db-card__desc">
            {cluster.engineLabel} · {cluster.tableCount} 张表
          </p>
        </div>
        <button
          type="button"
          className="ds-db-card__action"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          <RightOutlined className={open ? 'ds-db-card__chev ds-db-card__chev--open' : 'ds-db-card__chev'} />
          <span>{open ? '收起' : '表'}</span>
        </button>
      </div>

      {open && (
        <ul className="ds-db-card__tables">
          {cluster.items.map((ds) => (
            <li key={ds.id} className="ds-table-mini">
              <button type="button" className="ds-table-mini__body" onClick={() => onPreview(ds)}>
                <TableOutlined className="ds-table-mini__icon" />
                <span className="ds-table-mini__name" title={ds.name}>{ds.name}</span>
                <span className="ds-table-mini__meta">
                  {ds.row_count.toLocaleString()} 行
                </span>
              </button>
              <Popconfirm title="删除该表？" onConfirm={() => onDelete(ds.id)}>
                <button
                  type="button"
                  className="ds-table-mini__del"
                  aria-label="删除"
                  onClick={(e) => e.stopPropagation()}
                >
                  <DeleteOutlined />
                </button>
              </Popconfirm>
            </li>
          ))}
        </ul>
      )}

      <div className="ds-db-card__foot">
        <span className="ds-db-card__chip">{cluster.sideLabel}</span>
        <span className="ds-db-card__chip">{cluster.engineLabel}</span>
        <span className="ds-db-card__chip ds-db-card__chip--accent">
          {cluster.totalRows.toLocaleString()} 行
        </span>
        {cluster.items.some((d) => /结算行明细|收入台账明细/.test(d.name)) && (
          <span className="ds-db-card__chip ds-db-card__chip--ok">含主核对表</span>
        )}
      </div>
    </article>
  )
}
