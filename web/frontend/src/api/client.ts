export type QueryValue = string | number | boolean | null | undefined

export interface RequestOptions {
  method?: string
  query?: Record<string, QueryValue>
  json?: unknown
  form?: FormData
  headers?: Record<string, string>
  signal?: AbortSignal
  /** Do not bounce to /login on 401 (used by the login page and /auth/me). */
  skipAuthRedirect?: boolean
}

export class ApiError extends Error {
  status: number
  detail: string
  body: unknown

  constructor(status: number, detail: string, body?: unknown) {
    super(detail || `请求失败 (${status})`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail || `请求失败 (${status})`
    this.body = body
  }
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = path.startsWith('/') ? path : `/${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.append(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

async function parseError(res: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    const text = await res.text()
    if (!text) return new ApiError(res.status, res.statusText)
    try {
      body = JSON.parse(text)
    } catch {
      return new ApiError(res.status, text.slice(0, 400), text)
    }
    const detail = (body as { detail?: unknown })?.detail
    if (typeof detail === 'string') return new ApiError(res.status, detail, body)
    if (Array.isArray(detail)) {
      const msg = detail
        .map((d: unknown) => {
          if (typeof d === 'string') return d
          const item = d as { msg?: string; loc?: unknown[] }
          const loc = Array.isArray(item.loc) ? item.loc.join('.') : ''
          return [loc, item.msg].filter(Boolean).join(': ')
        })
        .join('; ')
      return new ApiError(res.status, msg || res.statusText, body)
    }
    return new ApiError(res.status, res.statusText, body)
  } catch {
    return new ApiError(res.status, res.statusText)
  }
}

const APP_BASE = (import.meta.env.BASE_URL || '/').replace(/\/$/, '')

/** Build an absolute browser path under the Vite/router base (e.g. /ui/login). */
export function appUrl(path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`
  return `${APP_BASE}${suffix}` || '/'
}

/** Strip the Vite/router base from a browser pathname so router.push stays inside the app. */
export function stripAppBase(pathname: string): string {
  if (APP_BASE && (pathname === APP_BASE || pathname.startsWith(`${APP_BASE}/`))) {
    return pathname.slice(APP_BASE.length) || '/'
  }
  return pathname || '/'
}

function redirectToLogin(): void {
  if (typeof window === 'undefined') return
  const loginPath = appUrl('/login')
  const path = stripAppBase(window.location.pathname)
  if (path === '/login' || path.startsWith('/login/')) return
  const target = encodeURIComponent(path + window.location.search + window.location.hash)
  window.location.assign(`${loginPath}?redirect=${target}`)
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers ?? {})
  let body: BodyInit | undefined

  if (options.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(options.json)
  } else if (options.form !== undefined) {
    body = options.form
  }

  let res: Response
  try {
    res = await fetch(buildUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers,
      body,
      credentials: 'include',
      signal: options.signal,
    })
  } catch (error) {
    if ((error as Error)?.name === 'AbortError') throw error
    throw new ApiError(0, '无法连接后端服务，请检查服务是否已启动', error)
  }

  if (!res.ok) {
    if (res.status === 401 && !options.skipAuthRedirect) redirectToLogin()
    throw await parseError(res)
  }

  if (res.status === 204) return undefined as T
  const contentType = res.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    return (await res.json()) as T
  }
  return (await res.text()) as unknown as T
}

export const api = {
  get<T>(path: string, query?: Record<string, QueryValue>, options: RequestOptions = {}) {
    return request<T>(path, { ...options, query })
  },
  post<T>(path: string, json?: unknown, options: RequestOptions = {}) {
    return request<T>(path, { ...options, method: 'POST', json })
  },
  put<T>(path: string, json?: unknown, options: RequestOptions = {}) {
    return request<T>(path, { ...options, method: 'PUT', json })
  },
  del<T>(path: string, options: RequestOptions = {}) {
    return request<T>(path, { ...options, method: 'DELETE' })
  },
  postForm<T>(path: string, form: FormData, options: RequestOptions = {}) {
    return request<T>(path, { ...options, method: 'POST', form })
  },
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return error.detail
    return error.status === 403 ? `${error.detail}（当前账号无权限）` : error.detail
  }
  if (error instanceof Error) return error.message
  return String(error)
}
