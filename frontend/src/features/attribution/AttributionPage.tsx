import { ExternalLink } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { useAttribution, type Attribution } from './api'

/**
 * The credit the Open Government Data License v1 requires of every page that shows the exchanges' open data, as the
 * server's settings give it: each providing agency with the datasets the site reads, the license's notice, its name and
 * its address.
 */
export function AttributionPage() {
  const { t } = useTranslation('attribution')
  const attribution = useAttribution()
  return (
    <div className="space-y-5 lg:space-y-6">
      <PageHeader title={t('title')} description={t('description')} />
      {attribution.isPending && <Skeleton className="h-96 rounded-2xl" />}
      {attribution.isError && <ErrorState error={attribution.error} title={t('failed')} onRetry={() => void attribution.refetch()} className="rounded-2xl border bg-card py-12" />}
      {attribution.data && <Credit attribution={attribution.data} />}
    </div>
  )
}

function Credit({ attribution }: { attribution: Attribution }) {
  const { t } = useTranslation('attribution')
  return (
    <div className="grid items-start gap-4 lg:gap-5 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <Panel className="xl:col-start-2 xl:row-start-1" title={t('license.title')} description={t('license.question')}>
        <div className="space-y-3 text-sm">
          <a href={attribution.license_url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-1.5 font-medium text-brand hover:underline md:min-h-0">
            {attribution.license}
            <ExternalLink aria-hidden className="size-3.5" />
          </a>
          <p className="font-mono text-xs break-all text-muted-foreground">{attribution.license_url}</p>
          <blockquote className="border-l-2 pl-3 text-pretty text-muted-foreground">{attribution.notice}</blockquote>
        </div>
      </Panel>
      <div className="grid gap-4 lg:gap-5 xl:col-start-1 xl:row-start-1">
        {attribution.providers.map((provider) => (
          <Panel key={provider.provider} title={provider.provider} description={t('provider.question', { count: provider.datasets.length })}>
            <ul className="grid gap-x-6 gap-y-1.5 text-sm @lg:grid-cols-2">
              {provider.datasets.map((dataset) => (
                <li key={dataset} className="border-l-2 pl-3 text-pretty">
                  {dataset}
                </li>
              ))}
            </ul>
          </Panel>
        ))}
      </div>
    </div>
  )
}
