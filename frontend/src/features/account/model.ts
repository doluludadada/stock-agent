import type { AccountHistory } from './api'

export type AccountValue = AccountHistory['current']
export type Position = AccountValue['positions'][number]

/** The positions, largest first. */
export function holdings(value: AccountValue): Position[] {
  return [...value.positions].sort((a, b) => b.market_value - a.market_value)
}

/** Unrealized profit or loss over what the open positions cost; 0 without positions. */
export function unrealizedRatio(value: AccountValue): number {
  const cost = value.positions.reduce((sum, position) => sum + position.cost_basis, 0)
  return cost ? value.unrealized_pnl / cost : 0
}

export interface EquityPoint {
  date: string
  value: number
}

/** The daily equity, oldest first. */
export function equityPoints(history: AccountHistory): EquityPoint[] {
  return Object.entries(history.equity_curve)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, value]) => ({ date, value: value.equity }))
}

export interface Move {
  change: number
  ratio: number
}

/** From one point to another; null when there is no earlier point or it was zero. */
export function moveBetween(from: EquityPoint | undefined, to: EquityPoint | undefined): Move | null {
  if (!from || !to || from.value === 0) return null
  return { change: to.value - from.value, ratio: (to.value - from.value) / from.value }
}

export interface TotalReturn {
  /** Equity minus the starting capital. */
  profit: number
  /** The profit over the starting capital. */
  ratio: number
  /** When the account opened, at its first read or its last reset. */
  since: string
}

/** The mock account's result since it opened; null at a real broker, which reports no opening. */
export function totalReturn(history: AccountHistory): TotalReturn | null {
  if (!history.opening || history.profit === null) return null
  const { initial_cash, opened_at } = history.opening
  return { profit: history.profit, ratio: initial_cash ? history.profit / initial_cash : 0, since: opened_at }
}

/** The starting capitals a reset offers, in NT$. The server takes any finite amount above zero. */
export const STARTING_CAPITALS: readonly number[] = [100_000, 500_000, 1_000_000, 3_000_000, 10_000_000]

/** The amounts to choose from, smallest first: the offered ones, and the account's own when it is none of them. */
export function startingCapitalChoices(current: number): number[] {
  return [...new Set([...STARTING_CAPITALS, current])].sort((a, b) => a - b)
}
