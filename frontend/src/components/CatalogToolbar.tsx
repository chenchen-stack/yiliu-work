import type { ReactNode } from 'react'

export type CatalogTabItem = { key: string; label: string; count?: number }
export type CatalogPillItem = { key: string; label: string; count?: number }

type Props = {
  tabs?: CatalogTabItem[]
  activeTab?: string
  onTabChange?: (key: string) => void
  pills?: CatalogPillItem[]
  activePill?: string
  onPillChange?: (key: string) => void
  hint?: string
  action?: ReactNode
}

export function CatalogToolbar({
  tabs,
  activeTab,
  onTabChange,
  pills,
  activePill,
  onPillChange,
  hint,
  action,
}: Props) {
  return (
    <div className="catalog-toolbar">
      {(tabs?.length || action) && (
        <div className="catalog-toolbar__row">
          {tabs && tabs.length > 0 && (
            <div className="catalog-tabs" role="tablist">
              {tabs.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === t.key}
                  className={`catalog-tab${activeTab === t.key ? ' catalog-tab--active' : ''}`}
                  onClick={() => onTabChange?.(t.key)}
                >
                  {t.label}
                  {t.count != null ? <span className="catalog-tab__count"> ({t.count})</span> : null}
                </button>
              ))}
            </div>
          )}
          {action ? <div className="catalog-toolbar__action">{action}</div> : null}
        </div>
      )}
      {pills && pills.length > 0 && (
        <div className="catalog-pills" role="group" aria-label="分类筛选">
          {pills.map((p) => (
            <button
              key={p.key}
              type="button"
              className={`catalog-pill${activePill === p.key ? ' catalog-pill--active' : ''}`}
              onClick={() => onPillChange?.(p.key)}
            >
              {p.label}
              {p.count != null ? <span className="catalog-pill__count"> ({p.count})</span> : null}
            </button>
          ))}
        </div>
      )}
      {hint ? (
        <p className="catalog-toolbar__hint-text">{hint}</p>
      ) : null}
    </div>
  )
}
