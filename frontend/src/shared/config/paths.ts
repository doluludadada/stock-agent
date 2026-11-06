/** The app's addresses. Features link with these; app/router maps the same paths to their pages. */
export const paths = {
  /** The home page. */
  runs: '/',
  run: (id: string) => `/runs/${encodeURIComponent(id)}`,
  market: '/market',
  strategies: '/strategies',
  newStrategy: '/strategies/new',
  copyStrategy: (id: string) => `/strategies/new?from=${encodeURIComponent(id)}`,
  copyBuiltInStrategy: (id: string) => `/strategies/new?builtin=${encodeURIComponent(id)}`,
  editStrategy: (id: string) => `/strategies/${encodeURIComponent(id)}/edit`,
  valuation: '/valuation',
  watchlist: '/watchlist',
  account: '/account',
  mySettings: '/settings',
  adminSettings: '/admin/settings',
  users: '/admin/users',
  stock: (code: string) => `/stocks/${encodeURIComponent(code)}`,
  setup: '/setup',
  signIn: '/sign-in',
  register: '/register',
  /** The sign-in page, returning to `next` afterwards. */
  signInThen: (next: string) => (next === '/' ? '/sign-in' : `/sign-in?next=${encodeURIComponent(next)}`),
}
