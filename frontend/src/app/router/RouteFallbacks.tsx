import { Ban, Compass, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useRouteError } from 'react-router'
import { useTranslation } from '@/i18n'
import { allows, useAudience, type Capability } from '@/shared/api'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { paths } from '@/shared/config/paths'

export function NotFoundRoute() {
  const { t } = useTranslation()
  return (
    <>
      <h1 className="sr-only">{t('notFound.title')}</h1>
      <StateBlock
        icon={Compass}
        title={t('notFound.title')}
        description={t('notFound.description')}
        className="rounded-2xl border bg-card py-12 shadow-card"
        action={
          <Button asChild variant="outline">
            <Link to={paths.market}>{t('notFound.home')}</Link>
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
        className="rounded-2xl border bg-card py-12 shadow-card"
        action={
          <Button type="button" variant="outline" onClick={() => window.location.assign(paths.market)}>
            {t('routeError.reload')}
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
  if (audience.isPending) return <Skeleton className="h-96 rounded-2xl" />
  if (audience.isError) return <ErrorState error={audience.error} title={t('audience.failed')} onRetry={() => void audience.refetch()} className="rounded-2xl border bg-card py-12" />
  if (allows(audience.data, capability)) return children
  return (
    <>
      <h1 className="sr-only">{title}</h1>
      <StateBlock
        icon={Ban}
        title={title}
        description={reason}
        className="rounded-2xl border bg-card py-12 shadow-card"
        action={
          <>
            <Button asChild variant="outline">
              <Link to={paths.market}>{t('notFound.home')}</Link>
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
