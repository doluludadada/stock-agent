import { createBrowserRouter } from 'react-router'
import { AppShell } from '../layouts/AppShell'
import { NotFoundRoute, RouteErrorBoundary } from './RouteFallbacks'

/** Each route module composes its features and loads on first visit. */
export const router = createBrowserRouter([
  {
    element: <AppShell />,
    errorElement: <RouteErrorBoundary />,
    children: [
      {
        errorElement: <RouteErrorBoundary />,
        children: [
          { index: true, lazy: () => import('./routes/overview').then((m) => ({ Component: m.OverviewRoute })) },
          { path: 'strategies', lazy: () => import('./routes/strategies').then((m) => ({ Component: m.StrategyLibraryRoute })) },
          { path: 'strategies/new', lazy: () => import('./routes/strategies').then((m) => ({ Component: m.NewStrategyRoute })) },
          { path: 'strategies/:id/edit', lazy: () => import('./routes/strategies').then((m) => ({ Component: m.EditStrategyRoute })) },
          { path: 'runs', lazy: () => import('./routes/runs').then((m) => ({ Component: m.RunsRoute })) },
          { path: 'runs/:runId', lazy: () => import('./routes/runs').then((m) => ({ Component: m.RunRoute })) },
          { path: 'valuation', lazy: () => import('./routes/valuation').then((m) => ({ Component: m.ValuationRoute })) },
          { path: 'watchlist', lazy: () => import('./routes/watchlist').then((m) => ({ Component: m.WatchlistRoute })) },
          { path: 'account', lazy: () => import('./routes/account').then((m) => ({ Component: m.AccountRoute })) },
          { path: 'admin/settings', lazy: () => import('./routes/admin').then((m) => ({ Component: m.AdminSettingsRoute })) },
          { path: 'stocks/:code', lazy: () => import('./routes/stock').then((m) => ({ Component: m.StockRoute })) },
          { path: '*', element: <NotFoundRoute /> },
        ],
      },
    ],
  },
])
