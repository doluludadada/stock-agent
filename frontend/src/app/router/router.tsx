import { createBrowserRouter } from 'react-router'
import { AppShell } from '../layouts/AppShell'
import { AuthLayout } from '../layouts/AuthLayout'
import { NotFoundRoute, RouteErrorBoundary } from './RouteFallbacks'
import { AuthGate, RegisterRoute, SetupRoute, SignInRoute } from './routes/auth'

/** Each route module composes its features and loads on first visit. */
export const router = createBrowserRouter([
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
              { path: 'strategies', lazy: () => import('./routes/strategies').then((m) => ({ Component: m.StrategyLibraryRoute })) },
              { path: 'strategies/new', lazy: () => import('./routes/strategies').then((m) => ({ Component: m.NewStrategyRoute })) },
              { path: 'strategies/:id/edit', lazy: () => import('./routes/strategies').then((m) => ({ Component: m.EditStrategyRoute })) },
              { path: 'runs', lazy: () => import('./routes/runs').then((m) => ({ Component: m.RunsRoute })) },
              { path: 'runs/:runId', lazy: () => import('./routes/runs').then((m) => ({ Component: m.RunRoute })) },
              { path: 'valuation', lazy: () => import('./routes/valuation').then((m) => ({ Component: m.ValuationRoute })) },
              { path: 'watchlist', lazy: () => import('./routes/watchlist').then((m) => ({ Component: m.WatchlistRoute })) },
              { path: 'account', lazy: () => import('./routes/account').then((m) => ({ Component: m.AccountRoute })) },
              { path: 'admin/settings', lazy: () => import('./routes/admin').then((m) => ({ Component: m.AdminSettingsRoute })) },
              { path: 'admin/users', lazy: () => import('./routes/users').then((m) => ({ Component: m.UsersRoute })) },
              { path: 'stocks/:code', lazy: () => import('./routes/stock').then((m) => ({ Component: m.StockRoute })) },
              { path: '*', element: <NotFoundRoute /> },
            ],
          },
        ],
      },
    ],
  },
])
