import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { cn } from '@/shared/lib/utils'

/** Under every page: the credit the open data's license asks for, as a link to its page, and that nothing here is advice. */
export function SiteFooter({ className }: { className?: string }) {
  const { t } = useTranslation()
  return (
    <footer className={cn('flex flex-col gap-2 border-t pt-4 text-xs text-muted-foreground md:flex-row md:items-start md:justify-between md:gap-6', className)}>
      <p className="max-w-prose text-pretty">{t('footer.notAdvice')}</p>
      <Link to={paths.attribution} className="inline-flex min-h-11 shrink-0 items-center font-medium text-foreground underline-offset-4 hover:text-brand hover:underline md:min-h-0">
        {t('footer.attribution')}
      </Link>
    </footer>
  )
}
