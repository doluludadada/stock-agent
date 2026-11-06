import type { components, paths } from './schema.gen'
import { session } from './session'

/**
 * The one HTTP transport: same-origin `/v1` paths (the Vite dev server and the production reverse proxy forward
 * them to the backend), the session cookie the server set at sign-in, typed bodies from the generated OpenAPI
 * contract, abort signals, and one error type. Feature `api` modules own their endpoints, query keys and mapping.
 */

type Method = 'get' | 'post' | 'put' | 'patch' | 'delete'

type Operation<P extends keyof paths, M extends Method> = paths[P] extends Record<M, infer Op> ? Op : never

type JsonContent<R> = R extends { content: { 'application/json': infer Body } } ? Body : never

type Success<Op> = Op extends { responses: infer R }
  ? 200 extends keyof R
    ? JsonContent<R[200]>
    : 201 extends keyof R
      ? JsonContent<R[201]>
      : 202 extends keyof R
        ? JsonContent<R[202]>
        : 204 extends keyof R
          ? undefined
          : never
  : never

type RequestBody<Op> = Op extends { requestBody: { content: { 'application/json': infer Body } } } ? Body : never

type Query<Op> = Op extends { parameters: { query?: infer Q } } ? Q : never

/**
 * 401: no valid session, the only answer that signs the app out. 403: signed in but not allowed, which never does.
 * 429: too many attempts or runs; `retryAfter` says how long to wait when the server told.
 */
export type ApiErrorKind = 'unauthorized' | 'forbidden' | 'notFound' | 'conflict' | 'invalid' | 'rateLimited' | 'unavailable' | 'network' | 'server'

/** The stable name of a refusal, which the server sends next to its words: switch on this, never on `detail`. */
export type ErrorCode = components['schemas']['ErrorCode']

/** Every code of the contract once: the compiler refuses this table when the contract adds or drops one. */
const ERROR_CODES = {
  sign_in_required: true,
  sign_in_refused: true,
  sign_in_throttled: true,
  registration_closed: true,
  setup_code_refused: true,
  already_set_up: true,
  user_exists: true,
  last_administrator: true,
  unknown_host: true,
  app_request_required: true,
  administrators_only: true,
  real_broker_refused: true,
  mock_broker_only: true,
  realtime_quotes_unavailable: true,
  mops_unavailable: true,
  password_required: true,
  password_refused: true,
  settings_file_refused: true,
  settings_file_missing: true,
  settings_conflict: true,
  settings_edit_refused: true,
  settings_refused: true,
  technical_settings_conflict: true,
  ai_model_not_offered: true,
  run_in_progress: true,
  too_many_runs: true,
  listing_unavailable: true,
  not_found: true,
  invalid_request: true,
  body_too_large: true,
  request_refused: true,
} as const satisfies Record<ErrorCode, true>

function isErrorCode(value: unknown): value is ErrorCode {
  return typeof value === 'string' && Object.hasOwn(ERROR_CODES, value)
}

function codeOf(body: unknown): ErrorCode | null {
  const code = typeof body === 'object' && body !== null && 'code' in body ? body.code : null
  return isErrorCode(code) ? code : null
}

export interface FieldProblem {
  location: (string | number)[]
  message: string
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status: number
  readonly problems: FieldProblem[]
  /** Seconds until the server takes the request again, from a 429's Retry-After. */
  readonly retryAfter: number | null
  /** The refusal's JSON body as the server sent it, for a feature that reads more than `detail`; null when it had none. */
  readonly body: unknown
  /** The refusal's code from its body; null for a lost connection, a body without one, or a code this build does not know. */
  readonly code: ErrorCode | null

  constructor(kind: ApiErrorKind, status: number, message: string, problems: FieldProblem[] = [], retryAfter: number | null = null, body: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
    this.problems = problems
    this.retryAfter = retryAfter
    this.body = body
    this.code = codeOf(body)
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
  if (status === 429) return 'rateLimited'
  if (status === 502 || status === 503 || status === 504) return 'unavailable'
  return 'server'
}

function retryAfterOf(response: Response): number | null {
  const seconds = Number(response.headers.get('Retry-After'))
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null
}

async function errorFrom(response: Response): Promise<ApiError> {
  const kind = kindOf(response.status)
  const retryAfter = retryAfterOf(response)
  const body: unknown = await response.json().catch(() => null)
  const detail = typeof body === 'object' && body !== null && 'detail' in body ? body.detail : null
  if (Array.isArray(detail)) {
    const problems = detail.map((item: { loc?: (string | number)[]; msg?: string }) => ({
      location: item.loc ?? [],
      message: item.msg ?? '',
    }))
    return new ApiError(kind, response.status, problems.map((problem) => problem.message).join('; '), problems, retryAfter, body)
  }
  return new ApiError(kind, response.status, typeof detail === 'string' ? detail : response.statusText, [], retryAfter, body)
}

interface RequestOptions<Op> {
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

/**
 * Every write carries `X-Requested-With: stock-agent`, which another site cannot add without a CORS preflight the API
 * never grants (the CSRF check). A 401 ends the session the request was sent in, never one started since.
 */
export async function apiRequest<P extends keyof paths, M extends Method>(
  method: M,
  path: P,
  options: RequestOptions<Operation<P, M>> = {},
): Promise<Success<Operation<P, M>>> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'get') headers['X-Requested-With'] = 'stock-agent'
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  const sentIn = session.generation()

  let response: Response
  try {
    response = await fetch(urlOf(path, options.params, options.query as object | undefined), {
      method: method.toUpperCase(),
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      credentials: 'same-origin',
      cache: 'no-store',
    })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError('network', 0, error instanceof Error ? error.message : 'network error')
  }

  if (!response.ok) {
    const error = await errorFrom(response)
    if (error.kind === 'unauthorized') session.expire(sentIn)
    throw error
  }
  if (response.status === 204) return undefined as Success<Operation<P, M>>
  return (await response.json()) as Success<Operation<P, M>>
}
