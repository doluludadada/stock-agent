import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { cn } from '@/shared/lib/utils'

/**
 * Said under the title of each technical-strategy page (the runs, the library, the backtest, the designer): their
 * built-in strategies did not profit in a backtest, and the ranking is where the app's attention moved. A reader who
 * lands on one by a bookmark learns it there.
 */
export function TechnicalStrategyNote({ className }: { className?: string }) {
  const { t } = useTranslation()
  return (
    <p className={cn('text-sm text-pretty text-muted-foreground', className)}>
      {t('technicalNote.text')}{' '}
      <Link to={paths.ranking} className="font-medium whitespace-nowrap text-brand hover:underline">
        {t('technicalNote.link')}
      </Link>
    </p>
  )
}
