import { Sparkles } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { useFormat } from '@/shared/lib/format'
import { Badge } from './badge'

/** That a text is the AI's, which model wrote it and when: the label every AI text on the site carries. */
export function AiByline({ model, writtenAt }: { model: string; writtenAt?: string | null }) {
  const { t } = useTranslation()
  const format = useFormat()
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-pretty text-muted-foreground">
      <Badge variant="secondary">
        <Sparkles aria-hidden />
        {t('ai.generated')}
      </Badge>
      <span className="font-mono break-all">{model}</span>
      {writtenAt && <time dateTime={writtenAt}>{t('ai.writtenAt', { time: format.monthDayTime(writtenAt) })}</time>}
    </p>
  )
}
