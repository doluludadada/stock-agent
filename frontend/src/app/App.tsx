import { createBrowserRouter, RouterProvider } from 'react-router'
import { AppProviders } from './providers/AppProviders'
import { routes } from './router/router'

const router = createBrowserRouter(routes)

export function App() {
  return (
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>
  )
}
