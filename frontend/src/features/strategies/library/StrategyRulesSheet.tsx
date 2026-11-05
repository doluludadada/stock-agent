import { useTranslation } from '@/i18n'
import { Badge } from '@/shared/ui/badge'
import { ScrollArea } from '@/shared/ui/scroll-area'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/shared/ui/sheet'
import { describeIndicator } from '../model/describe'
import type { IndicatorConfig, Strategy } from '../model/types'
import { requiredBars } from '../model/validate'
import { useFormulaText, useStrategyLabels } from '../use-formula-text'
import { RuleSummaryList } from './RuleSummaryList'

interface StrategyRulesSheetProps {
  strategy: Strategy | null
  onOpenChange: (open: boolean) => void
}

export function StrategyRulesSheet({ strategy, onOpenChange }: StrategyRulesSheetProps) {
  const { t } = useTranslation('strategies')
  const text = useFormulaText()
  const labels = useStrategyLabels()
  return (
    <Sheet open={strategy !== null} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 sm:max-w-lg">
        {strategy && (
          <>
            <SheetHeader className="border-b">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="font-normal">
                  <span className="font-mono">{strategy.id}</span>
                </Badge>
              </div>
              <SheetTitle className="text-xl">{labels.name(strategy)}</SheetTitle>
              <SheetDescription>{labels.purpose(strategy) || t('sheet.noDescription')}</SheetDescription>
            </SheetHeader>
            <ScrollArea className="min-h-0 flex-1">
              <div className="space-y-6 p-4">
                <section>
                  <h3 className="eyebrow mb-3">{t('sheet.rules', { count: strategy.rules.length })}</h3>
                  <RuleSummaryList strategy={strategy} named />
                </section>
                <section>
                  <h3 className="eyebrow mb-3">{t('sheet.indicators')}</h3>
                  <ul className="flex flex-wrap gap-2">
                    {(Object.values(strategy.indicators) as IndicatorConfig[]).map((config, index) => (
                      <li key={index} className="rounded-md border px-2 py-1 font-mono text-xs">
                        {describeIndicator(config, text)}
                      </li>
                    ))}
                  </ul>
                </section>
                <section className="grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-xl border p-3">
                    <div className="text-xs text-muted-foreground">{t('sheet.requiredBars')}</div>
                    <div className="tabular mt-1 font-semibold">{t('bars', { count: requiredBars(strategy) })}</div>
                  </div>
                  <div className="rounded-xl border p-3">
                    <div className="text-xs text-muted-foreground">{t('sheet.baseScore')}</div>
                    <div className="tabular mt-1 font-semibold">{strategy.scoring.baseScore}</div>
                  </div>
                </section>
              </div>
            </ScrollArea>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
