import { Check, Copy, Eye, Megaphone, Pencil, Shield, Sparkles, Trash2, Zap, Scale, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { cn } from '@/shared/lib/utils'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { Stat } from '@/shared/ui/stat'
import { BUILT_IN_IDS, type BuiltInId } from '../model/settings'
import type { Strategy } from '../model/types'
import { requiredBars } from '../model/validate'
import { useStrategyLabels } from '../use-formula-text'
import { RuleSummaryList } from './RuleSummaryList'

const BUILTIN_ICON: Record<BuiltInId, LucideIcon> = { conservative: Shield, balanced: Scale, aggressive: Zap }

interface StrategyCardProps {
  strategy: Strategy
  /** An official built-in strategy: read-only, so it can only be viewed and copied. */
  official?: boolean
  active?: boolean
  buzz?: boolean
  busy?: boolean
  copyHref: string
  editHref?: string
  onActivate?: () => void
  onSetBuzz?: () => void
  onViewRules: () => void
  onDelete?: () => void
  /** Why the strategy cannot be deleted now, shown instead of the delete action. */
  deleteBlocked?: string
}

export function StrategyCard(props: StrategyCardProps) {
  const { strategy, official = false, active = false, buzz = false, busy = false, copyHref, editHref } = props
  const { t } = useTranslation('strategies')
  const labels = useStrategyLabels()
  const builtInId = BUILT_IN_IDS.find((id) => id === strategy.id)
  const Icon = builtInId ? BUILTIN_ICON[builtInId] : Sparkles
  const name = labels.name(strategy)

  return (
    <article className={cn('flex h-full flex-col gap-3 rounded-xl border bg-card p-4 shadow-card', active && 'border-primary/50')} aria-label={name}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <Icon aria-hidden className={cn('size-4 shrink-0', active ? 'text-primary' : 'text-muted-foreground')} />
          <h3 className="truncate font-semibold">{name}</h3>
          <span className="shrink-0 text-xs text-muted-foreground">{t(official ? 'card.official' : 'card.custom')}</span>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1">
          {active && (
            <Badge className="gap-1">
              <Check aria-hidden className="size-3" />
              {t('card.active')}
            </Badge>
          )}
          {buzz && (
            <Badge variant="outline" className="gap-1 border-gold/40 text-gold">
              <Megaphone aria-hidden className="size-3" />
              {t('card.buzz')}
            </Badge>
          )}
        </div>
      </div>

      <p className="line-clamp-2 text-sm text-pretty text-muted-foreground">
        {labels.purpose(strategy) || t('card.noDescription')}
      </p>

      <div aria-label={t('card.preview')}>
        <RuleSummaryList strategy={strategy} limit={3} />
        {strategy.rules.length > 3 && (
          <p className="mt-1.5 text-xs text-faint">{t('card.moreRules', { count: strategy.rules.length - 3 })}</p>
        )}
      </div>

      <dl className="mt-auto grid grid-cols-3 gap-2 border-t pt-3">
        <Stat label={t('card.rules')}>{strategy.rules.length}</Stat>
        <Stat label={t('card.indicators')}>{Object.keys(strategy.indicators).length}</Stat>
        <Stat label={t('card.bars')}>{requiredBars(strategy)}</Stat>
      </dl>

      <div className="flex flex-wrap gap-1.5">
        {!official &&
          (active ? (
            <Button type="button" size="xs" variant="secondary" disabled>
              <Check aria-hidden />
              {t('action.inUse')}
            </Button>
          ) : (
            <Button type="button" size="xs" onClick={props.onActivate} disabled={busy}>
              {t('action.activate')}
            </Button>
          ))}
        {!official && !buzz && (
          <Button type="button" size="xs" variant="outline" onClick={props.onSetBuzz} disabled={busy}>
            <Megaphone aria-hidden />
            {t('action.setBuzz')}
          </Button>
        )}
        {editHref ? (
          <Button asChild size="xs" variant="outline">
            <Link to={editHref}>
              <Pencil aria-hidden />
              {t('action.edit')}
            </Link>
          </Button>
        ) : (
          <Button type="button" size="xs" variant="outline" onClick={props.onViewRules}>
            <Eye aria-hidden />
            {t('action.viewRules')}
          </Button>
        )}
        <Button asChild size="xs" variant="ghost">
          <Link to={copyHref} aria-label={t('action.copyNamed', { name })}>
            <Copy aria-hidden />
            {t(official ? 'action.copyToCustom' : 'action.duplicate')}
          </Link>
        </Button>
        {props.onDelete && (
          <Button
            type="button"
            size="icon-xs"
            variant="ghost"
            className="ml-auto text-muted-foreground hover:text-destructive"
            onClick={props.onDelete}
            disabled={busy || props.deleteBlocked !== undefined}
            title={props.deleteBlocked}
            aria-label={props.deleteBlocked ? `${t('action.deleteNamed', { name })}: ${props.deleteBlocked}` : t('action.deleteNamed', { name })}
          >
            <Trash2 aria-hidden />
          </Button>
        )}
      </div>
    </article>
  )
}
