import { useTranslation } from '@/i18n'
import { CHART_RANGE_KEYS, type ChartRange } from '@/shared/lib/chart-range'
import { Tabs, TabsList, TabsTrigger } from './tabs'

export function RangeTabs({ value, onChange, label }: { value: ChartRange; onChange: (range: ChartRange) => void; label: string }) {
  const { t } = useTranslation()
  return (
    <Tabs value={value} onValueChange={(next) => onChange(next as ChartRange)}>
      <TabsList aria-label={label} className="h-7">
        {CHART_RANGE_KEYS.map((range) => (
          <TabsTrigger key={range} value={range} className="tabular px-2 text-xs">
            {t(`range.${range}`)}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  )
}
