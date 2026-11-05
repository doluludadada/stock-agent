import { Compass, TriangleAlert } from 'lucide-react'
import { Link, useRouteError } from 'react-router'
import { useTranslation } from '@/i18n'
import { Button } from '@/shared/ui/button'
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
        className="rounded-xl border py-10"
        action={
          <Button asChild variant="outline" size="sm">
            <Link to={paths.overview}>{t('notFound.home')}</Link>
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
        className="rounded-xl border py-10"
        action={
          <Button type="button" variant="outline" size="sm" onClick={() => window.location.assign(paths.overview)}>
            {t('routeError.reload')}
          </Button>
        }
      />
    </div>
  )
}
