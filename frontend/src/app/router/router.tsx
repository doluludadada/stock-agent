import type { ComponentType } from 'react'
import type { RouteObject } from 'react-router'
import { AppShell } from '../layouts/AppShell'
import { AuthLayout } from '../layouts/AuthLayout'
import { paths } from '@/shared/config/paths'
import { pageEntries, type Page, type PageEntry } from '../pages'
import { NotFoundRoute, RequireFeature, RouteErrorBoundary } from './RouteFallbacks'
import { AuthGate, RegisterRoute, SetupRoute, SignInRoute } from './routes/auth'

/**
 * A page's module. A failed import resolves to nothing once stale-build.ts has taken it for a reload; when the user
 * stays on the page instead, the route's error page shows rather than an empty one.
 */
async function loaded(load: PageEntry['load']) {
  const Component: ComponentType | undefined = await load()
  if (!Component) throw new Error("The page's code did not load")
  return { Component }
}

/** A page's route: its module loads on first visit, behind the gate of the page's features. */
function route(key: Page, { path, load }: PageEntry): RouteObject {
  const at = path === paths.home ? { index: true as const } : { path }
  return { element: <RequireFeature page={key} />, children: [{ ...at, lazy: () => loaded(load) }] }
}

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
              ...pageEntries.map(([key, page]) => route(key, page)),
              { path: '*', element: <NotFoundRoute /> },
            ],
          },
        ],
      },
    ],
  },
]
