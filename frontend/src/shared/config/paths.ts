/** The addresses that carry a value. The page table gives these to the router; a link fills one through `paths`. */
export const patterns = {
  run: '/runs/:runId',
  editStrategy: '/strategies/:id/edit',
  stock: '/stocks/:code',
} as const

const fill = (pattern: string, value: string) => pattern.replace(/:\w+/, () => encodeURIComponent(value))

/** The app's addresses. Features link with these, and `app/pages.ts` maps the same addresses to their pages. */
export const paths = {
  home: '/',
  market: '/market',
  world: '/world',
  runs: '/runs',
  run: (id: string) => fill(patterns.run, id),
  strategies: '/strategies',
  newStrategy: '/strategies/new',
  copyStrategy: (id: string) => `/strategies/new?from=${encodeURIComponent(id)}`,
  copyBuiltInStrategy: (id: string) => `/strategies/new?builtin=${encodeURIComponent(id)}`,
  editStrategy: (id: string) => fill(patterns.editStrategy, id),
  backtest: '/backtest',
  savedBacktest: (id: string) => `/backtest?id=${encodeURIComponent(id)}`,
  ranking: '/ranking',
  valuation: '/valuation',
  watchlist: '/watchlist',
  holdings: '/holdings',
  account: '/account',
  brokerage: '/account/sinopac',
  mySettings: '/settings',
  adminSettings: '/admin/settings',
  users: '/admin/users',
  stock: (code: string) => fill(patterns.stock, code),
  attribution: '/attribution',
  setup: '/setup',
  signIn: '/sign-in',
  register: '/register',
  /** The sign-in page, returning to `next` afterwards. */
  signInThen: (next: string) => (next === '/' ? '/sign-in' : `/sign-in?next=${encodeURIComponent(next)}`),
}
