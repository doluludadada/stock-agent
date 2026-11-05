import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { cn } from '@/shared/lib/utils'
import { paths } from '@/shared/config/paths'

export function BrandMark({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation()
  return (
    <Link to={paths.overview} className="flex items-center gap-2.5 rounded-md" aria-label={t('brand.home')}>
      <span className="grid size-7 place-items-center rounded-lg bg-jade-soft">
        <svg viewBox="0 0 24 24" aria-hidden className="size-4.5 text-jade">
          <path d="M3 16.5 8 11l4 3.5 7-8" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="19" cy="6.5" r="1.8" className="fill-gold" />
        </svg>
      </span>
      <span className={cn('leading-tight', compact && 'max-sm:sr-only')}>
        <span className="block text-sm font-semibold tracking-tight">Stock Agent</span>
        <span className="block text-[0.6875rem] text-muted-foreground">{t('brand.tagline')}</span>
      </span>
    </Link>
  )
}
