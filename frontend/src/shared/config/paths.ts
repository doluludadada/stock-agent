/** The app's addresses. Features link with these; app/router maps the same paths to their pages. */
export const paths = {
  /** The home page: what changed since the last visit, card by card. */
  home: '/',
  market: '/market',
  runs: '/runs',
  run: (id: string) => `/runs/${encodeURIComponent(id)}`,
  strategies: '/strategies',
  newStrategy: '/strategies/new',
  copyStrategy: (id: string) => `/strategies/new?from=${encodeURIComponent(id)}`,
  copyBuiltInStrategy: (id: string) => `/strategies/new?builtin=${encodeURIComponent(id)}`,
  editStrategy: (id: string) => `/strategies/${encodeURIComponent(id)}/edit`,
  backtest: '/backtest',
  savedBacktest: (id: string) => `/backtest?id=${encodeURIComponent(id)}`,
  /** The monthly ranking by revenue and nearness to the high, with its record against the benchmark. */
  ranking: '/ranking',
  valuation: '/valuation',
  watchlist: '/watchlist',
  /** The user's holdings as one portfolio: the brokerage account's, the mock account's and the ones entered by hand. */
  holdings: '/holdings',
  account: '/account',
  /** The SinoPac account as the broker reports it. */
  brokerage: '/account/sinopac',
  mySettings: '/settings',
  adminSettings: '/admin/settings',
  users: '/admin/users',
  stock: (code: string) => `/stocks/${encodeURIComponent(code)}`,
  /** The open data's providers, datasets and license, which every page credits through its footer. */
  attribution: '/attribution',
  setup: '/setup',
  signIn: '/sign-in',
  register: '/register',
  /** The sign-in page, returning to `next` afterwards. */
  signInThen: (next: string) => (next === '/' ? '/sign-in' : `/sign-in?next=${encodeURIComponent(next)}`),
}
