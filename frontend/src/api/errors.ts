function detailFromPayload(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((d) =>
      typeof d === 'object' && d && 'msg' in d ? String((d as { msg: string }).msg) : String(d),
    )
    if (parts.length) return parts.join('; ')
  }
  if (detail && typeof detail === 'object' && 'msg' in detail) {
    return String((detail as { msg: string }).msg)
  }
  return null
}

/** Extract readable message from FastAPI / axios / fetch errors */
export function formatApiError(e: unknown, fallback = '请求失败'): string {
  const err = e as { response?: { status?: number; data?: { detail?: unknown } }; message?: string }
  const fromAxios = detailFromPayload(err.response?.data?.detail)
  if (fromAxios) return fromAxios

  const raw = err instanceof Error ? err.message : typeof e === 'string' ? e : err.message
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as { detail?: unknown }
      const fromJson = detailFromPayload(parsed.detail)
      if (fromJson) return fromJson
    } catch {
      /* plain text body */
    }
    if (raw.includes('Failed to fetch') || raw.includes('NetworkError') || raw.includes('ECONNREFUSED')) {
      return '无法连接后端，请确认已启动 backend（默认端口 8000）'
    }
    if (raw === 'Not Found' || raw.includes('"detail":"Not Found"')) {
      return '对话测试接口未就绪，请重启后端（backend\\run_dev.bat）后再试'
    }
    if (!/^HTTP \d+$/i.test(raw.trim())) return raw
  }

  const status = err.response?.status
  if (status === 404) return '接口不存在（404），请重启后端后再试'
  if (status === 401 || status === 403) return '未登录或权限不足，请重新登录'
  return fallback
}
