import type { RouteObject } from 'react-router'
import { AppShell } from '../layouts/AppShell'
import { AuthLayout } from '../layouts/AuthLayout'
import { NotFoundRoute, RouteErrorBoundary } from './RouteFallbacks'
import { AuthGate, RegisterRoute, SetupRoute, SignInRoute } from './routes/auth'

/** Each route module composes its features and loads on first visit. */
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
              { index: true, lazy: () => import('./routes/overview').then((m) => ({ Component: m.OverviewRoute })) },
              { path: 'market', lazy: () => import('./routes/overview').then((m) => ({ Component: m.MarketRedirect })) },
              { path: 'runs', lazy: () => import('./routes/runs').then((m) => ({ Component: m.RunsRoute })) },
              { path: 'strategies', lazy: () => import('./routes/strategies').then((m) => ({ Component: m.StrategyLibraryRoute })) },
              { path: 'strategies/new', lazy: () => import('./routes/strategies').then((m) => ({ Component: m.NewStrategyRoute })) },
              { path: 'strategies/:id/edit', lazy: () => import('./routes/strategies').then((m) => ({ Component: m.EditStrategyRoute })) },
              { path: 'backtest', lazy: () => import('./routes/backtest').then((m) => ({ Component: m.BacktestRoute })) },
              { path: 'runs/:runId', lazy: () => import('./routes/runs').then((m) => ({ Component: m.RunRoute })) },
              { path: 'valuation', lazy: () => import('./routes/valuation').then((m) => ({ Component: m.ValuationRoute })) },
              { path: 'watchlist', lazy: () => import('./routes/watchlist').then((m) => ({ Component: m.WatchlistRoute })) },
              { path: 'account', lazy: () => import('./routes/account').then((m) => ({ Component: m.AccountRoute })) },
              { path: 'settings', lazy: () => import('./routes/settings').then((m) => ({ Component: m.MySettingsRoute })) },
              { path: 'admin/settings', lazy: () => import('./routes/admin').then((m) => ({ Component: m.AdminSettingsRoute })) },
              { path: 'admin/users', lazy: () => import('./routes/users').then((m) => ({ Component: m.UsersRoute })) },
              { path: 'stocks/:code', lazy: () => import('./routes/stock').then((m) => ({ Component: m.StockRoute })) },
              { path: 'attribution', lazy: () => import('./routes/attribution').then((m) => ({ Component: m.AttributionRoute })) },
              { path: '*', element: <NotFoundRoute /> },
            ],
          },
        ],
      },
    ],
  },
]
