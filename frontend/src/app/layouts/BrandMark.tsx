import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { cn } from '@/shared/lib/utils'
import { paths } from '@/shared/config/paths'

/** The logo and name; `compact` keeps the logo only, for the tablet rail. */
export function BrandMark({ compact = false, className }: { compact?: boolean; className?: string }) {
  const { t } = useTranslation()
  return (
    <Link to={paths.runs} className={cn('flex min-h-11 items-center gap-2.5 rounded-lg', className)} aria-label={t('brand.home')}>
      <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-brand text-primary-foreground">
        <svg viewBox="0 0 24 24" aria-hidden className="size-4.5">
          <path d="M3 16.5 8 11l4 3.5 7-8" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="19" cy="6.5" r="1.9" fill="currentColor" />
        </svg>
      </span>
      {!compact && (
        <span className="leading-tight">
          <span className="block text-sm font-semibold tracking-tight">Stock Agent</span>
          <span className="block text-[0.6875rem] text-muted-foreground">{t('brand.tagline')}</span>
        </span>
      )}
    </Link>
  )
}
