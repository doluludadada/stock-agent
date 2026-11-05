import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MotionConfig } from 'motion/react'
import { useEffect, type ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import { isApiError, session } from '@/shared/api'
import { ThemeProvider } from '@/shared/lib/theme'
import { Toaster } from '@/shared/ui/sonner'
import { TooltipProvider } from '@/shared/ui/tooltip'

const i18n = initI18n()

/**
 * Server state lives in one query cache. Query keys start with their scope ('public', 'owner' or 'admin'), so the
 * private scopes' cached data is dropped the moment another user signs in, the user signs out or the server ends the
 * session, and the administrator's when a role changes: one user's answers never show to the next.
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

function viewer(): string {
  const current = session.current()
  return `${session.generation()}:${current.status === 'signedIn' ? current.user.role : ''}`
}

function useScopedCache() {
  useEffect(() => {
    let seen = viewer()
    return session.subscribe(() => {
      const now = viewer()
      if (now === seen) return
      seen = now
      queryClient.removeQueries({ queryKey: ['owner'] })
      queryClient.removeQueries({ queryKey: ['admin'] })
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
