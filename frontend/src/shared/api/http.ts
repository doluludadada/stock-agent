import type { paths } from './schema.gen'
import { session, type Scope } from './session'

/**
 * The one HTTP transport: same-origin `/v1` paths (the Vite dev server and the production reverse proxy forward
 * them to the backend), the scope's bearer token, typed bodies from the generated OpenAPI contract, abort signals,
 * and one error type. Feature `api` modules own their endpoints, query keys and mapping.
 */

type Method = 'get' | 'post' | 'put' | 'delete'

type Operation<P extends keyof paths, M extends Method> = paths[P] extends Record<M, infer Op> ? Op : never

type JsonContent<R> = R extends { content: { 'application/json': infer Body } } ? Body : never

type Success<Op> = Op extends { responses: infer R }
  ? 200 extends keyof R
    ? JsonContent<R[200]>
    : 202 extends keyof R
      ? JsonContent<R[202]>
      : never
  : never

type RequestBody<Op> = Op extends { requestBody: { content: { 'application/json': infer Body } } } ? Body : never

type Query<Op> = Op extends { parameters: { query?: infer Q } } ? Q : never

export type ApiErrorKind = 'unauthorized' | 'forbidden' | 'notFound' | 'conflict' | 'invalid' | 'unavailable' | 'network' | 'server'

export interface FieldProblem {
  location: (string | number)[]
  message: string
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status: number
  readonly problems: FieldProblem[]

  constructor(kind: ApiErrorKind, status: number, message: string, problems: FieldProblem[] = []) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
    this.problems = problems
  }
}

export function isApiError(error: unknown, kind?: ApiErrorKind): error is ApiError {
  return error instanceof ApiError && (kind === undefined || error.kind === kind)
}

function kindOf(status: number): ApiErrorKind {
  if (status === 401) return 'unauthorized'
  if (status === 403) return 'forbidden'
  if (status === 404) return 'notFound'
  if (status === 409) return 'conflict'
  if (status === 422) return 'invalid'
  if (status === 502 || status === 503 || status === 504) return 'unavailable'
  return 'server'
}

async function errorFrom(response: Response): Promise<ApiError> {
  const kind = kindOf(response.status)
  let detail: unknown = null
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail
  } catch {
    detail = null
  }
  if (Array.isArray(detail)) {
    const problems = detail.map((item: { loc?: (string | number)[]; msg?: string }) => ({
      location: item.loc ?? [],
      message: item.msg ?? '',
    }))
    return new ApiError(kind, response.status, problems.map((problem) => problem.message).join('; '), problems)
  }
  const listed = (detail as { problems?: unknown } | null)?.problems
  if (Array.isArray(listed)) {
    const problems = listed.map((message) => ({ location: [], message: String(message) }))
    return new ApiError(kind, response.status, problems.map((problem) => problem.message).join('; '), problems)
  }
  return new ApiError(kind, response.status, typeof detail === 'string' ? detail : response.statusText)
}

interface RequestOptions<Op> {
  scope?: Scope
  params?: Record<string, string>
  query?: Query<Op>
  body?: RequestBody<Op>
  signal?: AbortSignal
}

function urlOf(path: string, params: Record<string, string> = {}, query: object | undefined): string {
  const filled = path.replace(/\{(\w+)\}/g, (_, name: string) => encodeURIComponent(params[name] ?? ''))
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null) continue
    for (const item of Array.isArray(value) ? value : [value]) search.append(key, String(item))
  }
  const text = search.toString()
  return text ? `${filled}?${text}` : filled
}

export async function apiRequest<P extends keyof paths, M extends Method>(
  method: M,
  path: P,
  options: RequestOptions<Operation<P, M>> = {},
): Promise<Success<Operation<P, M>>> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = options.scope ? session.token(options.scope) : null
  if (options.scope && token === null) throw new ApiError('unauthorized', 401, 'locked')
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(urlOf(path, options.params, options.query as object | undefined), {
      method: method.toUpperCase(),
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      credentials: 'omit',
      cache: 'no-store',
    })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError('network', 0, error instanceof Error ? error.message : 'network error')
  }

  if (!response.ok) {
    const error = await errorFrom(response)
    if (error.kind === 'unauthorized' && options.scope && token) session.reject(options.scope, token)
    throw error
  }
  return (await response.json()) as Success<Operation<P, M>>
}
