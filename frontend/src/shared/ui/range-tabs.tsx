import { useTranslation } from '@/i18n'
import { CHART_RANGE_KEYS, type ChartRange } from '@/shared/lib/chart-range'
import { Segmented } from './segmented'

/** The chart range, as a segmented control that spans the card on a phone. */
export function RangeTabs({ value, onChange, label, className }: { value: ChartRange; onChange: (range: ChartRange) => void; label: string; className?: string }) {
  const { t } = useTranslation()
  return <Segmented value={value} onChange={onChange} label={label} className={className} options={CHART_RANGE_KEYS.map((range) => ({ value: range, label: t(`range.${range}`) }))} />
}
