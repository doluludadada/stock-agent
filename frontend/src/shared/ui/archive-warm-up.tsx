import { Hourglass } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { useAllows, useArchiveStatus } from '@/shared/api'
import { cn } from '@/shared/lib/utils'

/**
 * A site on open data only reads its daily history from the archive it keeps from its first day. Until that holds
 * the sessions the strategies need, this says how far it has come; anywhere else, and after that, it shows nothing.
 */
export function ArchiveWarmUp({ className }: { className?: string }) {
  const { t } = useTranslation()
  const openDataOnly = useAllows('open_data_only')
  const status = useArchiveStatus(openDataOnly)
  if (!openDataOnly || !status.data || status.data.sessions >= status.data.needed) return null
  const { sessions, needed } = status.data
  return (
    <section aria-label={t('warmUp.label')} className={cn('flex items-start gap-3 rounded-xl border border-gold/35 bg-gold-soft px-4 py-3', className)}>
      <Hourglass aria-hidden className="mt-0.5 size-4 shrink-0 text-gold" />
      <div className="min-w-0 flex-1 space-y-2">
        <p className="text-sm font-medium">
          {t('warmUp.title')} <span className="tabular">{t('warmUp.count', { sessions, needed })}</span>
        </p>
        <div role="progressbar" aria-label={t('warmUp.label')} aria-valuemin={0} aria-valuemax={needed} aria-valuenow={sessions} className="h-1.5 overflow-hidden rounded-full bg-background/70">
          <div className="h-full rounded-full bg-gold" style={{ width: `${(sessions / needed) * 100}%` }} />
        </div>
        <p className="text-xs text-pretty text-muted-foreground">{t('warmUp.description', { needed })}</p>
      </div>
    </section>
  )
}
