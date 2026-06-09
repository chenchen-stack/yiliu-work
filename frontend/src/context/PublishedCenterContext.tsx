import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { BusinessCenter, getBusinessCenterByCode, getPublishedCenters } from '../api/client'
import { REVENUE_CENTER_CODE, createShowModule } from '../utils/pageModules'

type PublishedCenterContextValue = {
  center: BusinessCenter | null
  loading: boolean
  refresh: () => Promise<void>
  showModule: (key: string) => boolean
  published: boolean
}

const PublishedCenterContext = createContext<PublishedCenterContextValue | null>(null)

export function PublishedCenterProvider({ children }: { children: React.ReactNode }) {
  const [center, setCenter] = useState<BusinessCenter | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      try {
        const detail = await getBusinessCenterByCode(REVENUE_CENTER_CODE)
        setCenter(detail)
        return
      } catch {
        const list = await getPublishedCenters()
        setCenter(list.find((c) => c.code === REVENUE_CENTER_CODE) || list[0] || null)
      }
    } catch {
      setCenter(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh().catch(console.error)
  }, [refresh])

  const showModule = useMemo(() => createShowModule(center), [center])

  const value = useMemo(
    () => ({
      center,
      loading,
      refresh,
      showModule,
      published: !!center && center.status === 'published',
    }),
    [center, loading, refresh, showModule],
  )

  return (
    <PublishedCenterContext.Provider value={value}>
      {children}
    </PublishedCenterContext.Provider>
  )
}

export function usePublishedCenter() {
  const ctx = useContext(PublishedCenterContext)
  if (!ctx) {
    throw new Error('usePublishedCenter must be used within PublishedCenterProvider')
  }
  return ctx
}
