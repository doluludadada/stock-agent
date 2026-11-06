import { Info } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { cn } from '@/shared/lib/utils'

/** Said beside every analysis result and stock report: what the page shows is research, not investment advice. */
export function NotAdviceNote({ className }: { className?: string }) {
  const { t } = useTranslation()
  return (
    <p className={cn('flex items-start gap-2 text-xs text-pretty text-muted-foreground', className)}>
      <Info aria-hidden className="mt-px size-3.5 shrink-0 text-gold" />
      {t('notAdvice')}
    </p>
  )
}
