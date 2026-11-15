import { useFormulaWords, type RankingFormula } from '@/shared/lib/ranking-formula'

/** What a ranking formula ranks by and when it holds cash, in one line. */
export function FormulaLine({ formula, className }: { formula: RankingFormula; className?: string }) {
  const words = useFormulaWords()
  return <span className={className}>{[words.factors(formula), words.cash(formula)].filter(Boolean).join(' · ')}</span>
}
