import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { isApiError, type FieldProblem } from '@/shared/api'
import { useKeptDraft } from '@/shared/lib/kept-draft'
import { useLeaveGuard } from '@/shared/lib/leave-guard'
import { newIds, ruleIndexOf } from '../api/mapping'
import { useSaveStrategySettings, useStrategySettings } from '../api/queries'
import { applyEdit, copyStrategy, createBlankStrategy, pruneEditorIndicators, type StrategyEdit } from '../model/edit'
import { isRefusal, withStrategy } from '../model/settings'
import type { IdFactory, Strategy, StrategySettings } from '../model/types'
import { errorsOf, validateStrategy } from '../model/validate'

/** A built-in id may also be an owner strategy's id, so a copy names which list its source comes from. */
export type BuilderMode = { type: 'blank' } | { type: 'copy'; source: 'owned' | 'builtIn'; id: string } | { type: 'edit'; id: string }

export type DraftSource = { status: 'ready'; strategy: Strategy; isNew: boolean } | { status: 'missing' }

export const draftIds: IdFactory = newIds()

/**
 * What the editor starts from: an owner strategy to edit, a copy of an owner or built-in strategy, or a blank one.
 * Copies get a new id, so saving never replaces their source. A copy of a built-in becomes the owner's own text, so its
 * rules take their names in the owner's language; the names of an owner strategy are already the owner's.
 */
export function resolveDraftSource(
  mode: BuilderMode,
  owned: readonly Strategy[],
  builtIns: readonly Strategy[],
  labels: { copyName: (source: Strategy) => string; ruleName: (strategyId: string, name: string) => string },
): DraftSource {
  if (mode.type === 'blank') return { status: 'ready', strategy: createBlankStrategy(draftIds), isNew: true }
  if (mode.type === 'edit') {
    const existing = owned.find((strategy) => strategy.id === mode.id)
    return existing ? { status: 'ready', strategy: structuredClone(existing), isNew: false } : { status: 'missing' }
  }
  const original = (mode.source === 'builtIn' ? builtIns : owned).find((strategy) => strategy.id === mode.id)
  if (!original) return { status: 'missing' }
  const copy = copyStrategy(original, { ids: draftIds, name: labels.copyName(original) })
  if (mode.source === 'owned') return { status: 'ready', strategy: copy, isNew: true }
  const rules = copy.rules.map((rule) => ({ ...rule, name: labels.ruleName(original.id, rule.name) }))
  return { status: 'ready', strategy: { ...copy, rules }, isNew: true }
}

type DraftState = { draft: Strategy; baseline: string }

/** `from` is the draft the save sent; an edit made while the save was in flight stays in the draft, unsaved. */
type DraftAction = { type: 'edit'; edit: StrategyEdit } | { type: 'saved'; from: Strategy; sent: Strategy }

function reducer(state: DraftState, action: DraftAction): DraftState {
  switch (action.type) {
    case 'edit':
      return { ...state, draft: applyEdit(state.draft, action.edit) }
    case 'saved':
      return { draft: state.draft === action.from ? action.sent : state.draft, baseline: JSON.stringify(action.sent) }
  }
}

export type SaveOutcome =
  | { ok: true; settings: StrategySettings }
  | { ok: false; reason: 'invalid' | 'full' | 'conflict' | 'notLoaded' }
  | { ok: false; reason: 'refused'; rules: (number | null)[] }
  | { ok: false; reason: 'failed'; error: unknown }

/** The rule each problem of a refused save is about, once; null stands for the strategy as a whole. */
function refusedRules(problems: readonly FieldProblem[], strategyIndex: number): (number | null)[] {
  return [...new Set(problems.map((problem) => ruleIndexOf(problem.location, strategyIndex)))]
}

/**
 * The draft of one strategy and its save. A save puts the draft into the latest settings the server sent, with
 * their revision. A 409 keeps the draft: the settings are refetched, then `conflict` turns on, so saving again puts
 * the same draft into the newer settings, keeping every other change the other save made.
 */
export function useStrategyDraft(initial: Strategy, name: string) {
  const settings = useStrategySettings()
  const mutation = useSaveStrategySettings()
  const keptDraft = useKeptDraft<Strategy>(`strategy:${name}`)
  const [state, dispatch] = useReducer(reducer, initial, (strategy) => ({ draft: keptDraft.restored ?? strategy, baseline: JSON.stringify(strategy) }))
  const [attempted, setAttempted] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [lastSaved, setLastSaved] = useState(initial)
  const kept = useMemo(() => new Set(Object.keys(initial.indicators)), [initial])
  const dirty = JSON.stringify(state.draft) !== state.baseline
  const { blocker, release } = useLeaveGuard(dirty, 'leaves')
  const latestDraft = useRef(state.draft)
  useEffect(() => {
    latestDraft.current = state.draft
    keptDraft.track(dirty ? state.draft : null)
  }, [dirty, state.draft, keptDraft])

  // What a save sends: the draft without the indicators no condition reads, which no field shows either.
  const sent = useMemo(() => pruneEditorIndicators(state.draft, kept), [state.draft, kept])
  const issues = useMemo(() => validateStrategy(sent), [sent])
  const edit = useCallback((change: StrategyEdit) => dispatch({ type: 'edit', edit: change }), [])

  const save = useCallback(async (): Promise<SaveOutcome> => {
    setAttempted(true)
    if (errorsOf(issues).length > 0) return { ok: false, reason: 'invalid' }
    if (!settings.data) return { ok: false, reason: 'notLoaded' }
    const strategy = sent
    const next = withStrategy(settings.data, strategy)
    if (isRefusal(next)) return { ok: false, reason: 'full' }
    try {
      const saved = await mutation.mutateAsync(next)
      if (latestDraft.current === state.draft) release('route')
      setConflict(false)
      dispatch({ type: 'saved', from: state.draft, sent: strategy })
      setLastSaved(saved.strategies.find((item) => item.id === strategy.id) ?? strategy)
      return { ok: true, settings: saved }
    } catch (error) {
      if (isApiError(error, 'conflict')) {
        await settings.refetch()
        setConflict(true)
        return { ok: false, reason: 'conflict' }
      }
      if (isApiError(error, 'invalid')) {
        const index = next.strategies.findIndex((item) => item.id === strategy.id)
        return { ok: false, reason: 'refused', rules: refusedRules(error.problems, index) }
      }
      return { ok: false, reason: 'failed', error }
    }
  }, [issues, sent, mutation, settings, state.draft, release])

  /** True when the server's copy of this strategy changed since this draft last read or saved it. */
  const serverChanged = useMemo(() => {
    const current = settings.data?.strategies.find((item) => item.id === lastSaved.id)
    return conflict && current !== undefined && JSON.stringify(current) !== JSON.stringify(lastSaved)
  }, [conflict, lastSaved, settings.data])

  return {
    draft: state.draft,
    edit,
    issues,
    attempted,
    dirty,
    save,
    saving: mutation.isPending,
    conflict,
    serverChanged,
    revision: settings.data?.revision,
    blocker,
  }
}
