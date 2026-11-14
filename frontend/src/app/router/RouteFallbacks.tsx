import { Ban, Compass, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, Outlet, useRouteError } from 'react-router'
import { useTranslation } from '@/i18n'
import { usePageTitle } from '@/shared/lib/page-title'
import { allows, useAudience, useShown, type Capability } from '@/shared/api'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { PageSkeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { paths } from '@/shared/config/paths'
import { PAGES, type Page } from '../pages'

export function NotFoundRoute() {
  const { t } = useTranslation()
  usePageTitle(t('notFound.title'))
  return (
    <>
      <h1 className="sr-only">{t('notFound.title')}</h1>
      <StateBlock
        icon={Compass}
        title={t('notFound.title')}
        description={t('notFound.description')}
        framed
        action={
          <Button asChild variant="outline">
            <Link to={paths.home}>{t('notFound.home')}</Link>
          </Button>
        }
      />
    </>
  )
}

export function RouteErrorBoundary() {
  const { t } = useTranslation()
  const error = useRouteError()
  console.error(error)
  return (
    <div className="mx-auto max-w-xl p-6">
      <StateBlock
        tone="danger"
        icon={TriangleAlert}
        title={t('routeError.title')}
        description={t('routeError.description')}
        framed
        action={
          <Button asChild variant="outline">
            {/* A plain link, not the router's: the page loads again, which clears what broke. */}
            <a href={paths.home}>{t('notFound.home')}</a>
          </Button>
        }
      />
    </div>
  )
}

/**
 * A page only some audiences offer. Where the site's audience does not allow it, a link to it says why in one short
 * panel instead of opening a page whose every request the server refuses.
 */
export function RequireCapability({ capability, title, reason, children }: { capability: Capability; title: string; reason: string; children: ReactNode }) {
  const { t } = useTranslation()
  const audience = useAudience()
  if (audience.isPending) return <PageSkeleton />
  if (audience.isError) return <ErrorState error={audience.error} title={t('audience.failed')} onRetry={() => void audience.refetch()} framed />
  if (allows(audience.data, capability)) return children
  return (
    <>
      <h1 className="sr-only">{title}</h1>
      <StateBlock
        icon={Ban}
        title={title}
        description={reason}
        framed
        action={
          <>
            <Button asChild variant="outline">
              <Link to={paths.home}>{t('notFound.home')}</Link>
            </Button>
            <Button asChild variant="ghost">
              <Link to={paths.attribution}>{t('footer.attribution')}</Link>
            </Button>
          </>
        }
      />
    </>
  )
}

/**
 * The route of a page whose features the administrator can hide. To a viewer who sees none of them a link to it
 * answers like an address that does not exist, so the page tells nothing about what the site keeps for others.
 */
export function RequireFeature({ page }: { page: Page }) {
  const { t } = useTranslation()
  const shown = useShown()
  const { features } = PAGES[page]
  const children = <Outlet />
  if (features.length === 0) return children
  if (shown.pending) return <PageSkeleton />
  if (shown.error) return <ErrorState error={shown.error} title={t('audience.failed')} onRetry={shown.retry} framed />
  return shown.shows(features) ? children : <NotFoundRoute />
}
