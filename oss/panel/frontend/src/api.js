// API client for the Flask backend. Throws Error(message) on failure.
// A 401 redirects to the login page (unless already there).

async function req(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (r.status === 401 && !location.hash.includes('login')) {
    location.hash = '#/login'
    throw new Error('请先登录')
  }
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.error || `请求失败 (${r.status})`)
  return data
}

export const get = (p) => req('GET', p)
export const post = (p, b) => req('POST', p, b)
export const put = (p, b) => req('PUT', p, b)
export const patch = (p, b) => req('PATCH', p, b)
export const delReq = (p) => req('DELETE', p)

export function fmtBytes(n) {
  n = n || 0
  if (n > 1e9) return (n / 1e9).toFixed(2) + ' GB'
  if (n > 1e6) return (n / 1e6).toFixed(1) + ' MB'
  if (n > 1e3) return Math.round(n / 1e3) + ' KB'
  return n + ' B'
}

export function fmtMs(ms) {
  if (ms == null) return '—'
  return Math.round(ms) + ' ms'
}
