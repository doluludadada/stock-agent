import { QueryClientProvider } from '@tanstack/react-query'
import { MotionConfig } from 'motion/react'
import { useEffect, type ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import { ThemeProvider } from '@/shared/lib/theme'
import { Toaster } from '@/shared/ui/sonner'
import { TooltipProvider } from '@/shared/ui/tooltip'
import { createQueryClient, scopeCacheToSession } from './query-client'

const i18n = initI18n()

const queryClient = createQueryClient()

export function AppProviders({ children }: { children: ReactNode }) {
  useEffect(() => scopeCacheToSession(queryClient), [])
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
