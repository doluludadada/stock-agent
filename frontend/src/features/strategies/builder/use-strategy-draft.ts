import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { useBlocker } from 'react-router'
import { isApiError, type FieldProblem } from '@/shared/api'
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
 * Copies get a new id, so saving never replaces their source.
 */
export function resolveDraftSource(
  mode: BuilderMode,
  owned: readonly Strategy[],
  builtIns: readonly Strategy[],
  copyName: (source: Strategy) => string,
): DraftSource {
  if (mode.type === 'blank') return { status: 'ready', strategy: createBlankStrategy(draftIds), isNew: true }
  if (mode.type === 'edit') {
    const existing = owned.find((strategy) => strategy.id === mode.id)
    return existing ? { status: 'ready', strategy: structuredClone(existing), isNew: false } : { status: 'missing' }
  }
  const original = (mode.source === 'builtIn' ? builtIns : owned).find((strategy) => strategy.id === mode.id)
  if (!original) return { status: 'missing' }
  return { status: 'ready', strategy: copyStrategy(original, { ids: draftIds, name: copyName(original) }), isNew: true }
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
  | { ok: false; reason: 'invalid' | 'full' | 'conflict' | 'locked' }
  | { ok: false; reason: 'refused'; problems: { rule: number | null; message: string }[] }
  | { ok: false; reason: 'failed'; error: unknown }

function refusedProblems(problems: readonly FieldProblem[], strategyIndex: number) {
  return problems.map((problem) => ({ rule: ruleIndexOf(problem.location, strategyIndex), message: problem.message }))
}

/**
 * The draft of one strategy and its save. A save puts the draft into the latest settings the server sent, with
 * their revision. A 409 keeps the draft: the settings are refetched, then `conflict` turns on, so saving again puts
 * the same draft into the newer settings, keeping every other change the other save made.
 */
export function useStrategyDraft(initial: Strategy) {
  const settings = useStrategySettings()
  const mutation = useSaveStrategySettings()
  const [state, dispatch] = useReducer(reducer, initial, (strategy) => ({ draft: strategy, baseline: JSON.stringify(strategy) }))
  const [attempted, setAttempted] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [lastSaved, setLastSaved] = useState(initial)
  const kept = useMemo(() => new Set(Object.keys(initial.indicators)), [initial])
  const dirty = JSON.stringify(state.draft) !== state.baseline
  const dirtyRef = useRef(dirty)
  const latestDraft = useRef(state.draft)
  useEffect(() => {
    dirtyRef.current = dirty
    latestDraft.current = state.draft
  }, [dirty, state.draft])

  const issues = useMemo(() => validateStrategy(state.draft), [state.draft])
  const edit = useCallback((change: StrategyEdit) => dispatch({ type: 'edit', edit: change }), [])

  const save = useCallback(async (): Promise<SaveOutcome> => {
    setAttempted(true)
    if (errorsOf(issues).length > 0) return { ok: false, reason: 'invalid' }
    if (!settings.data) return { ok: false, reason: 'locked' }
    const strategy = pruneEditorIndicators(state.draft, kept)
    const next = withStrategy(settings.data, strategy)
    if (isRefusal(next)) return { ok: false, reason: 'full' }
    try {
      const saved = await mutation.mutateAsync(next)
      dirtyRef.current = latestDraft.current !== state.draft
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
        return { ok: false, reason: 'refused', problems: refusedProblems(error.problems, index) }
      }
      return { ok: false, reason: 'failed', error }
    }
  }, [issues, kept, mutation, settings, state.draft])

  /** True when the server's copy of this strategy changed since this draft last read or saved it. */
  const serverChanged = useMemo(() => {
    const current = settings.data?.strategies.find((item) => item.id === lastSaved.id)
    return conflict && current !== undefined && JSON.stringify(current) !== JSON.stringify(lastSaved)
  }, [conflict, lastSaved, settings.data])

  useEffect(() => {
    if (!dirty) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty])

  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirtyRef.current && currentLocation.pathname !== nextLocation.pathname)

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
