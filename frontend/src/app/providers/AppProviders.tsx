import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MotionConfig } from 'motion/react'
import { useEffect, type ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import { isApiError, session, type Scope } from '@/shared/api'
import { ThemeProvider } from '@/shared/lib/theme'
import { Toaster } from '@/shared/ui/sonner'
import { TooltipProvider } from '@/shared/ui/tooltip'

const i18n = initI18n()

/**
 * Server state lives in one query cache. Query keys start with their scope ('public', 'owner' or 'admin'), so a
 * scope's cached data is dropped the moment its token changes or the server rejects it.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (failures, error) => failures < 1 && (isApiError(error, 'network') || isApiError(error, 'unavailable')),
    },
    mutations: { retry: false },
  },
})

function useScopedCache() {
  useEffect(() => {
    const tokens: Record<Scope, string | null> = { owner: session.token('owner'), admin: session.token('admin') }
    return session.subscribe(() => {
      for (const scope of ['owner', 'admin'] as const) {
        const token = session.token(scope)
        if (token === tokens[scope]) continue
        tokens[scope] = token
        queryClient.removeQueries({ queryKey: [scope] })
      }
    })
  }, [])
}

export function AppProviders({ children }: { children: ReactNode }) {
  useScopedCache()
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <MotionConfig reducedMotion="user">
            <TooltipProvider delayDuration={250}>
              {children}
              <Toaster position="bottom-right" closeButton mobileOffset={{ bottom: 84 }} />
            </TooltipProvider>
          </MotionConfig>
        </ThemeProvider>
      </QueryClientProvider>
    </I18nextProvider>
  )
}
