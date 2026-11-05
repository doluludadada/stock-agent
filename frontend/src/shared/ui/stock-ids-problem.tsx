import { useTranslation } from '@/i18n'
import { MAX_STOCK_IDS, type StockIdList } from '@/shared/lib/stock-ids'

/** Why a typed list of stock ids cannot be sent: the tokens that are not ids, or too many ids. Empty when it can. */
export function StockIdsProblem({ id, list }: { id: string; list: StockIdList }) {
  const { t } = useTranslation()
  const problem =
    list.invalid.length > 0 ? t('stockIds.invalid', { ids: list.invalid.join(', ') }) : list.ids.length > MAX_STOCK_IDS ? t('stockIds.tooMany', { max: MAX_STOCK_IDS }) : ''
  return (
    <p id={id} className="w-full text-xs text-destructive empty:hidden" aria-live="polite">
      {problem}
    </p>
  )
}
