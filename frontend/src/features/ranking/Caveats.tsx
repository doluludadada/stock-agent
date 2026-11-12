import { TriangleAlert } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { NotAdviceNote } from '@/shared/ui/not-advice-note'
import { Panel } from '@/shared/ui/panel'
import { CAVEATS } from './model'

/** Why the record looks better than following the ranking would have been, said beside every result. */
export function Caveats({ className }: { className?: string }) {
  const { t } = useTranslation('ranking')
  return (
    <div id="ranking-caveats" className={className}>
      <Panel title={t('caveats.title')} description={t('caveats.question')}>
        <ul className="grid gap-x-8 gap-y-2.5 text-sm text-pretty @3xl:grid-cols-2">
          {CAVEATS.map((caveat) => (
            <li key={caveat} className="flex items-start gap-2">
              <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-gold" />
              <span>
                <span className="font-medium">{t(`caveats.${caveat}.title`)}</span> <span className="text-muted-foreground">{t(`caveats.${caveat}.detail`)}</span>
              </span>
            </li>
          ))}
        </ul>
        <NotAdviceNote className="mt-3 border-t pt-3" />
      </Panel>
    </div>
  )
}
