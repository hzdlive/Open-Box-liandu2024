// Open-Box 二开：面板管理 API 封装（Flask /api/*，同源 + cookie session）
export class ObxApiError extends Error {
  status: number
  constructor(status: number, msg: string) {
    super(msg)
    this.status = status
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...((init.headers as Record<string, string>) || {}) },
    ...init,
  })
  if (res.status === 401) throw new ObxApiError(401, 'login required')
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown>
  if (!res.ok) throw new ObxApiError(res.status, String(data.error || `request failed: ${res.status}`))
  return data as T
}

export const obxGet = <T>(path: string) => req<T>(path)
export const obxPost = <T>(path: string, body: unknown) =>
  req<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
export const obxPut = <T>(path: string, body: unknown) =>
  req<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) })
export const obxPatch = <T>(path: string, body: unknown) =>
  req<T>(path, { method: 'PATCH', body: JSON.stringify(body ?? {}) })
export const obxDel = <T>(path: string) => req<T>(path, { method: 'DELETE' })
