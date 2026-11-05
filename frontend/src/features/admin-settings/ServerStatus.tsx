import { HardDriveDownload, LoaderCircle, RefreshCw, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { useLocale, useTranslation } from '@/i18n'
import { formatMonthDayTime } from '@/shared/lib/format'
import { Button } from '@/shared/ui/button'
import { useReloadSettings } from './api'
import { ProblemList, type Reveal } from './CheckDetails'
import { currentRefusal, isLoadingFromDisk, reasonOf, type SettingsFileId, type SettingsOverview } from './model'

/** How long an edit on disk may wait for the server's own look before the page offers to load it now. */
const OFFER_LOAD_AFTER_MS = 8_000

/**
 * What the server does with the files on disk, said only when there is something to say: an edit made there that the
 * app would not start with, with its problems and a way to try again; an edit still loading; earlier settings still
 * finishing runs.
 */
export function ServerStatus({ overview, active, onReveal }: { overview: SettingsOverview; active: SettingsFileId; onReveal: Reveal }) {
  const { t } = useTranslation('admin')
  const locale = useLocale()
  const reload = useReloadSettings()
  const refusal = currentRefusal(overview)
  const loading = isLoadingFromDisk(overview)
  const [tried, setTried] = useState<string | null>(null)

  /**
   * The reload request loads the files on disk now, a refused edit included. Its answer is one of two overviews: one
   * that runs on the files (`refused` null), or one with the new refusal, which a try again then says it met.
   */
  const load = (again: boolean) =>
    reload.mutate(undefined, {
      onSuccess: (next) => {
        if (!next.refused) toast.success(t('disk.loaded'))
        else if (again) setTried(next.refused.at)
      },
    })

  if (refusal) {
    return (
      <section role="alert" aria-labelledby="disk-refused" className="space-y-3 rounded-2xl border border-destructive/30 bg-danger-soft p-4 md:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <TriangleAlert aria-hidden className="mt-0.5 size-5 shrink-0 text-destructive" />
            <div className="min-w-0 space-y-1">
              <h2 id="disk-refused" className="text-title font-semibold">
                {t('disk.refusedTitle')}
              </h2>
              <p className="text-sm text-pretty">{t('disk.refusedDescription', { time: formatMonthDayTime(locale, refusal.at) })}</p>
              <p className="text-sm text-pretty text-muted-foreground">{t('disk.refusedFix')}</p>
              {tried === refusal.at && <p className="text-sm text-muted-foreground">{t('disk.stillRefused', { time: formatMonthDayTime(locale, refusal.at) })}</p>}
              {reload.isError && <p className="text-sm text-destructive">{t('disk.retryFailed', { reason: reasonOf(reload.error, t) })}</p>}
            </div>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={() => load(true)} disabled={reload.isPending} className="bg-card">
            {reload.isPending ? <LoaderCircle aria-hidden className="animate-spin" /> : <RefreshCw aria-hidden />}
            {t('disk.retry')}
          </Button>
        </div>
        <div className="rounded-xl bg-card p-2">
          <ProblemList problems={refusal.problems} file={active} onReveal={onReveal} />
        </div>
      </section>
    )
  }

  if (!loading && overview.draining === 0) return null
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border bg-card px-3.5 py-2.5 text-sm" aria-live="polite">
      {loading ? (
        <>
          <LoaderCircle aria-hidden className="size-4 animate-spin text-muted-foreground" />
          <span>{t('disk.loading')}</span>
          <LoadNow onLoad={() => load(false)} pending={reload.isPending} />
        </>
      ) : (
        <span className="text-muted-foreground">{t('disk.draining', { count: overview.draining })}</span>
      )}
    </p>
  )
}

/** Offered once an edit on disk waited longer than the server's own look takes; it mounts when the wait begins. */
function LoadNow({ onLoad, pending }: { onLoad: () => void; pending: boolean }) {
  const { t } = useTranslation('admin')
  const [offered, setOffered] = useState(false)
  useEffect(() => {
    const timer = window.setTimeout(() => setOffered(true), OFFER_LOAD_AFTER_MS)
    return () => window.clearTimeout(timer)
  }, [])
  if (!offered) return null
  return (
    <Button type="button" variant="outline" size="sm" onClick={onLoad} disabled={pending}>
      <HardDriveDownload aria-hidden />
      {t('disk.loadNow')}
    </Button>
  )
}
