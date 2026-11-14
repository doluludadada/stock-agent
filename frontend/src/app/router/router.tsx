import type { ComponentType } from 'react'
import type { RouteObject } from 'react-router'
import { AppShell } from '../layouts/AppShell'
import { AuthLayout } from '../layouts/AuthLayout'
import type { Page } from '../pages'
import { NotFoundRoute, RequireFeature, RouteErrorBoundary } from './RouteFallbacks'
import { AuthGate, RegisterRoute, SetupRoute, SignInRoute } from './routes/auth'

/**
 * A page's route: its module loads on first visit, and it opens only for a viewer who sees one of the page's features
 * (`PAGE_FEATURES`); anyone else gets the not-found page.
 */
function page(key: Page, at: { index: true } | { path: string }, load: () => Promise<ComponentType>): RouteObject {
  return { element: <RequireFeature page={key} />, children: [{ ...at, lazy: () => load().then((Component) => ({ Component })) }] }
}

/** Each route module composes its features. */
export const routes: RouteObject[] = [
  {
    element: <AuthGate />,
    errorElement: <RouteErrorBoundary />,
    // The first route's code loads before it renders; the page stays blank for that moment.
    HydrateFallback: () => null,
    children: [
      {
        element: <AuthLayout />,
        children: [
          { path: 'setup', element: <SetupRoute /> },
          { path: 'sign-in', element: <SignInRoute /> },
          { path: 'register', element: <RegisterRoute /> },
        ],
      },
      {
        element: <AppShell />,
        children: [
          {
            errorElement: <RouteErrorBoundary />,
            children: [
              page('home', { index: true }, () => import('./routes/home').then((m) => m.HomeRoute)),
              page('overview', { path: 'market' }, () => import('./routes/overview').then((m) => m.OverviewRoute)),
              page('runs', { path: 'runs' }, () => import('./routes/runs').then((m) => m.RunsRoute)),
              page('strategies', { path: 'strategies' }, () => import('./routes/strategies').then((m) => m.StrategyLibraryRoute)),
              page('builder', { path: 'strategies/new' }, () => import('./routes/strategies').then((m) => m.NewStrategyRoute)),
              page('builder', { path: 'strategies/:id/edit' }, () => import('./routes/strategies').then((m) => m.EditStrategyRoute)),
              page('backtest', { path: 'backtest' }, () => import('./routes/backtest').then((m) => m.BacktestRoute)),
              page('ranking', { path: 'ranking' }, () => import('./routes/ranking').then((m) => m.RankingRoute)),
              page('run', { path: 'runs/:runId' }, () => import('./routes/runs').then((m) => m.RunRoute)),
              page('valuation', { path: 'valuation' }, () => import('./routes/valuation').then((m) => m.ValuationRoute)),
              page('watchlist', { path: 'watchlist' }, () => import('./routes/watchlist').then((m) => m.WatchlistRoute)),
              page('holdings', { path: 'holdings' }, () => import('./routes/holdings').then((m) => m.HoldingsRoute)),
              page('account', { path: 'account' }, () => import('./routes/account').then((m) => m.AccountRoute)),
              page('brokerage', { path: 'account/sinopac' }, () => import('./routes/account').then((m) => m.BrokerageAccountRoute)),
              page('settings', { path: 'settings' }, () => import('./routes/settings').then((m) => m.MySettingsRoute)),
              page('admin', { path: 'admin/settings' }, () => import('./routes/admin').then((m) => m.AdminSettingsRoute)),
              page('users', { path: 'admin/users' }, () => import('./routes/users').then((m) => m.UsersRoute)),
              page('stock', { path: 'stocks/:code' }, () => import('./routes/stock').then((m) => m.StockRoute)),
              page('attribution', { path: 'attribution' }, () => import('./routes/attribution').then((m) => m.AttributionRoute)),
              { path: '*', element: <NotFoundRoute /> },
            ],
          },
        ],
      },
    ],
  },
]
