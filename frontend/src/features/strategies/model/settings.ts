import { strategyToApi } from '../api/mapping'
import { LIMITS } from './catalog'
import type { Strategy, StrategyId, StrategySettings } from './types'

/**
 * Changes to the owner's saved settings. Each returns the whole next settings, carrying the revision it started
 * from, because the server replaces the settings as a whole and refuses a stale revision (409).
 */

export type SettingsRefusal = 'selected' | 'last' | 'full'

const sameStrategy = (left: Strategy, right: Strategy) => JSON.stringify(strategyToApi(left)) === JSON.stringify(strategyToApi(right))

/**
 * The owner's own strategies. A first read copies every built-in under its id, and such a copy is the built-in, so it
 * is not the owner's; a copy that no longer matches the built-in it came from is, so no edit hides behind its name.
 */
export function customStrategies(settings: StrategySettings, builtIns: readonly Strategy[]): Strategy[] {
  return settings.strategies.filter((strategy) => {
    const shipped = builtIns.find((builtIn) => builtIn.id === strategy.id)
    return !shipped || !sameStrategy(strategy, shipped)
  })
}

/** The built-in whose copy the owner has in use, or null while one of their own strategies is. */
export function builtInInUse(settings: StrategySettings, builtIns: readonly Strategy[]): Strategy | null {
  const active = settings.strategies.find((strategy) => strategy.id === settings.activeStrategyId)
  const shipped = builtIns.find((builtIn) => builtIn.id === settings.activeStrategyId)
  return active && shipped && sameStrategy(active, shipped) ? shipped : null
}

export function withStrategy(settings: StrategySettings, strategy: Strategy): StrategySettings | SettingsRefusal {
  const exists = settings.strategies.some((item) => item.id === strategy.id)
  if (!exists && settings.strategies.length >= LIMITS.maxStrategies) return 'full'
  const strategies = exists
    ? settings.strategies.map((item) => (item.id === strategy.id ? strategy : item))
    : [...settings.strategies, strategy]
  return { ...settings, strategies }
}

/** The strategy in use cannot go: every workflow would have none. Neither can the last one. */
export function withoutStrategy(settings: StrategySettings, id: StrategyId): StrategySettings | SettingsRefusal {
  const refusal = deletionRefusal(settings, id)
  if (refusal) return refusal
  return { ...settings, strategies: settings.strategies.filter((item) => item.id !== id) }
}

export function deletionRefusal(settings: StrategySettings, id: StrategyId): SettingsRefusal | null {
  if (settings.activeStrategyId === id) return 'selected'
  if (settings.strategies.length <= 1) return 'last'
  return null
}

export function withActive(settings: StrategySettings, id: StrategyId): StrategySettings {
  return { ...settings, activeStrategyId: id }
}

/**
 * Puts a built-in in use exactly as it ships. The owner's copy under its id comes back when deleted; a copy the owner
 * changed moves to `newId` and stays one of their own strategies.
 */
export function withBuiltInActive(settings: StrategySettings, builtIn: Strategy, newId: StrategyId): StrategySettings | SettingsRefusal {
  const copy = settings.strategies.find((strategy) => strategy.id === builtIn.id)
  const kept = copy && !sameStrategy(copy, builtIn) ? withStrategy(settings, { ...copy, id: newId }) : settings
  if (isRefusal(kept)) return kept
  const next = withStrategy(kept, builtIn)
  return isRefusal(next) ? next : withActive(next, builtIn.id)
}

export function isRefusal(value: StrategySettings | SettingsRefusal): value is SettingsRefusal {
  return typeof value === 'string'
}
