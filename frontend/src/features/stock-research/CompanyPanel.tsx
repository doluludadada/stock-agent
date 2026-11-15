import { Building2, ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from '@/i18n'
import { useFormat } from '@/shared/lib/format'
import { outboundUrl } from '@/shared/lib/outbound-url'
import { AiByline } from '@/shared/ui/ai-byline'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { useStockCompany } from './api'
import { companyCard, companyLinks, type CompanyProfile, type StockBrief, type StockCompanyAnswer } from './brief'
import { Sentences } from './BriefPanel'

/**
 * What the company is, in one card: the AI's company card, which the site writes once and keeps, then the facts of
 * its profile, then where both come from. The main business as the company filed it shows only while there is no
 * card, since the card says it. It reads what the site holds: opening the page fetches nothing from MOPS
 * or the document site and spends no AI call. The card's sentences and the main business are the AI's and the
 * company's own text and render as text.
 */
export function CompanyPanel({ stockId }: { stockId: string }) {
  const { t } = useTranslation('research')
  const company = useStockCompany(stockId)
  return (
    <Panel title={t('company.title')}>
      {company.data ? (
        <Company answer={company.data} />
      ) : company.isError ? (
        <ErrorState error={company.error} title={t('company.loadFailed')} onRetry={() => void company.refetch()} />
      ) : (
        <Skeleton className="h-32 rounded-lg" />
      )}
    </Panel>
  )
}

function Company({ answer }: { answer: StockCompanyAnswer }) {
  const { t } = useTranslation('research')
  const card = companyCard(answer)
  const { profile } = answer
  if (!card && !profile) return <StateBlock icon={Building2} title={t('company.none')} className="py-4" />
  return (
    <div className="space-y-4">
      {card && <Card card={card} />}
      {profile && <Facts profile={profile} withMainBusiness={!card} />}
      <Sources answer={answer} />
    </div>
  )
}

function Card({ card }: { card: StockBrief }) {
  return (
    <div className="space-y-2">
      <Sentences sentences={card.company ?? []} sources={card.sources ?? []} />
      <AiByline model={card.model} writtenAt={card.written_at} />
    </div>
  )
}

/** The profile's facts, each shown only where the site holds it; the main business is the company's own words. */
function Facts({ profile, withMainBusiness }: { profile: CompanyProfile; withMainBusiness: boolean }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const website = outboundUrl(profile.website ?? null)
  const facts: [string, ReactNode][] = [
    [t('company.founded'), profile.founded_on && format.date(profile.founded_on)],
    [t('company.listed'), profile.listed_on && format.date(profile.listed_on)],
    [t('company.capital'), typeof profile.paid_in_capital === 'number' && t('company.twd', { value: format.compact(profile.paid_in_capital) })],
    [t('company.chairman'), profile.chairman],
    [
      t('company.website'),
      website && (
        <a key="website" href={website} target="_blank" rel="noopener noreferrer nofollow" className="tap gap-1 break-all text-brand underline-offset-4 hover:underline">
          {new URL(website).hostname}
          <ExternalLink aria-hidden className="size-3.5 shrink-0" />
          <span className="sr-only">{t('common:opensSource')}</span>
        </a>
      ),
    ]
  ]
  const held = facts.filter(([, value]) => value)
  return (
    <div className="space-y-3">
      {withMainBusiness && profile.main_business && (
        <p className="text-sm leading-relaxed text-pretty break-words">
          <span className="text-muted-foreground">{t('company.mainBusiness')}</span> {profile.main_business}
        </p>
      )}
      {held.length > 0 && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 @md:grid-cols-3 @2xl:grid-cols-5">
          {held.map(([label, value]) => (
            <Stat key={label} label={label}>
              {value}
            </Stat>
          ))}
        </dl>
      )}
    </div>
  )
}

/** Where the facts come from: MOPS's page of the company and the document site's page that lists its annual report. */
function Sources({ answer }: { answer: StockCompanyAnswer }) {
  const { t } = useTranslation('research')
  const links = companyLinks(answer)
  if (links.length === 0) return null
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
      <span>{t('company.sources')}</span>
      {links.map((link) => (
        <a key={link.href} href={link.href} target="_blank" rel="noopener noreferrer nofollow" className="tap gap-1 font-medium text-brand underline-offset-4 hover:underline">
          {t(`brief.kind.${link.kind}`)}
          <ExternalLink aria-hidden className="size-3 shrink-0" />
          <span className="sr-only">{t('common:opensSource')}</span>
        </a>
      ))}
    </p>
  )
}
