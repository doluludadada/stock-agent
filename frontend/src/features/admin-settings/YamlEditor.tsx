import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { yaml } from '@codemirror/lang-yaml'
import { bracketMatching, HighlightStyle, indentUnit, syntaxHighlighting } from '@codemirror/language'
import { lintGutter, lintKeymap, setDiagnostics, type Diagnostic } from '@codemirror/lint'
import { highlightSelectionMatches, search, searchKeymap } from '@codemirror/search'
import { Annotation, Compartment, EditorState, RangeSet, StateEffect, StateField, type Text } from '@codemirror/state'
import { EditorView, GutterMarker, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumberMarkers, lineNumbers } from '@codemirror/view'
import { tags } from '@lezer/highlight'
import { useEffect, useImperativeHandle, useRef, type Ref } from 'react'
import type { LocatedProblem } from './model'

export interface YamlEditorHandle {
  /** Puts the caret at a 1-based line and column, scrolls it to the middle and focuses the editor. */
  reveal: (line: number, column: number) => void
}

interface YamlEditorProps {
  value: string
  onChange: (text: string) => void
  /** Ctrl+S or Cmd+S in the editor. */
  onSave: () => void
  problems: readonly LocatedProblem[]
  /** The 1-based lines of `value` that differ from the file it started from, marked beside their numbers. */
  changedLines: readonly number[]
  label: string
  /** The id of the text that describes the editor's keys, for screen readers. */
  describedBy?: string
  ref?: Ref<YamlEditorHandle>
}

/**
 * The settings file's text in CodeMirror 6: line numbers, YAML highlighting, search, undo, and each problem the server
 * located underlined at its line and column with a mark in the gutter. Colors are the design tokens, so the editor
 * follows the theme. Lines wrap: the files' long lines are comments.
 */
export function YamlEditor({ value, onChange, onSave, problems, changedLines, label, describedBy, ref }: YamlEditorProps) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const latest = useRef({ value, onChange, onSave, attributes: attributesOf(label, describedBy) })
  const attributes = useRef(new Compartment())
  useEffect(() => {
    latest.current = { value, onChange, onSave, attributes: attributesOf(label, describedBy) }
  })

  useEffect(() => {
    if (!host.current) return
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: latest.current.value,
        extensions: [
          lineNumbers(),
          highlightActiveLineGutter(),
          highlightActiveLine(),
          history(),
          indentUnit.of('  '),
          yaml(),
          syntaxHighlighting(highlightStyle),
          bracketMatching(),
          search({ top: true }),
          highlightSelectionMatches(),
          lintGutter(),
          changed,
          lineNumberMarkers.compute([changed], (state) => state.field(changed)),
          EditorView.lineWrapping,
          attributes.current.of(latest.current.attributes),
          keymap.of([{ key: 'Mod-s', preventDefault: true, run: () => (latest.current.onSave(), true) }, ...defaultKeymap, ...historyKeymap, ...searchKeymap, ...lintKeymap, indentWithTab]),
          EditorView.updateListener.of((update) => {
            if (update.docChanged && !update.transactions.some((transaction) => transaction.annotation(fromProps))) latest.current.onChange(update.state.doc.toString())
          }),
          theme,
        ],
      }),
    })
    view.current = editor
    return () => {
      editor.destroy()
      view.current = null
    }
  }, [])

  useEffect(() => {
    view.current?.dispatch({ effects: attributes.current.reconfigure(attributesOf(label, describedBy)) })
  }, [label, describedBy])

  useEffect(() => {
    const editor = view.current
    if (!editor || editor.state.doc.toString() === value) return
    editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value }, annotations: fromProps.of(true) })
  }, [value])

  useEffect(() => {
    const editor = view.current
    if (editor) editor.dispatch(setDiagnostics(editor.state, diagnosticsOf(problems, editor.state.doc)))
  }, [problems])

  useEffect(() => {
    view.current?.dispatch({ effects: markChanged.of(changedLines) })
  }, [changedLines])

  useImperativeHandle(ref, () => ({
    reveal: (line, column) => {
      const editor = view.current
      if (!editor) return
      const anchor = offsetOf(editor.state.doc, line, column)
      editor.dispatch({ selection: { anchor }, effects: EditorView.scrollIntoView(anchor, { y: 'center' }) })
      editor.focus()
    },
  }))

  return <div ref={host} className="h-full min-h-0" />
}

/** The editable area's name and description for screen readers; spelling help is off, as in code. */
function attributesOf(label: string, describedBy: string | undefined) {
  return EditorView.contentAttributes.of({ 'aria-label': label, ...(describedBy ? { 'aria-describedby': describedBy } : {}), spellcheck: 'false', autocapitalize: 'off', autocorrect: 'off' })
}

/** A line the reader changed: its number gets a bar in the brand color. */
class ChangedLine extends GutterMarker {
  override elementClass = 'cm-changedLine'
}
const changedLine = new ChangedLine()
const markChanged = StateEffect.define<readonly number[]>()

/** The changed lines from the last check, moved along with the edits made since, until the next check replaces them. */
const changed = StateField.define<RangeSet<GutterMarker>>({
  create: () => RangeSet.empty,
  update(marks, transaction) {
    let next = marks.map(transaction.changes)
    for (const effect of transaction.effects) {
      if (!effect.is(markChanged)) continue
      const { doc } = transaction.state
      next = RangeSet.of(effect.value.filter((line) => line >= 1 && line <= doc.lines).map((line) => changedLine.range(doc.line(line).from)), true)
    }
    return next
  },
})

/** Marks a change that came in through `value`, such as a newer file or a discard: it is not the reader's edit. */
const fromProps = Annotation.define<boolean>()

/** A 1-based line and column as an offset in the text, clamped to the text: the file may have changed since. */
function offsetOf(doc: Text, line: number, column: number): number {
  const target = doc.line(Math.min(Math.max(1, line), doc.lines))
  return target.from + Math.min(Math.max(0, column - 1), target.length)
}

/** Each problem underlines from its column to the end of its line, which holds the setting it names. */
function diagnosticsOf(problems: readonly LocatedProblem[], doc: Text): Diagnostic[] {
  return problems.map((problem) => {
    const from = offsetOf(doc, problem.line, problem.column)
    const end = doc.lineAt(from).to
    const to = Math.max(from + 1, from + doc.sliceString(from, end).trimEnd().length)
    return { from: Math.min(from, doc.length), to: Math.min(to, doc.length), severity: 'error', message: problem.path ? `${problem.path}: ${problem.message}` : problem.message }
  })
}

const highlightStyle = HighlightStyle.define([
  { tag: tags.definition(tags.propertyName), color: 'var(--color-brand)', fontWeight: '550' },
  { tag: tags.lineComment, color: 'var(--color-faint)', fontStyle: 'italic' },
  { tag: [tags.separator, tags.punctuation, tags.squareBracket, tags.brace], color: 'var(--muted-foreground)' },
  { tag: [tags.labelName, tags.typeName, tags.keyword, tags.meta], color: 'var(--color-gold)' },
])

const theme = EditorView.theme({
  '&': { height: '100%', backgroundColor: 'var(--card)', color: 'var(--foreground)', fontSize: '0.8125rem' },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': { fontFamily: 'var(--font-family-mono)', lineHeight: '1.65' },
  '.cm-content': { padding: '0.5rem 0', caretColor: 'var(--foreground)' },
  '.cm-line': { padding: '0 0.5rem 0 0.375rem' },
  '.cm-gutters': { backgroundColor: 'var(--muted)', color: 'var(--color-faint)', borderRight: '1px solid var(--border)' },
  '.cm-lineNumbers .cm-gutterElement': { padding: '0 0.25rem 0 0.375rem', minWidth: '2rem' },
  '@media (min-width: 48rem)': {
    '.cm-line': { padding: '0 0.75rem 0 0.5rem' },
    '.cm-lineNumbers .cm-gutterElement': { padding: '0 0.5rem 0 0.75rem', minWidth: '2.75rem' },
  },
  '.cm-activeLine': { backgroundColor: 'color-mix(in oklch, var(--foreground) 4%, transparent)' },
  '.cm-lineNumbers .cm-gutterElement.cm-changedLine': { boxShadow: 'inset 3px 0 0 var(--color-brand)', color: 'var(--foreground)' },
  '.cm-activeLineGutter': { backgroundColor: 'color-mix(in oklch, var(--foreground) 7%, transparent)', color: 'var(--foreground)' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--foreground)' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': { backgroundColor: 'var(--color-brand-soft)' },
  '.cm-selectionMatch': { backgroundColor: 'var(--color-brand-soft)' },
  '.cm-matchingBracket': { backgroundColor: 'var(--color-brand-soft)', outline: '1px solid color-mix(in oklch, var(--color-brand) 40%, transparent)' },
  '.cm-searchMatch': { backgroundColor: 'var(--color-gold-soft)', outline: '1px solid color-mix(in oklch, var(--color-gold) 45%, transparent)' },
  '.cm-searchMatch-selected': { backgroundColor: 'color-mix(in oklch, var(--color-gold) 30%, transparent)' },
  '.cm-lintRange-error': { backgroundImage: 'none', textDecoration: 'underline wavy var(--destructive)', textDecorationThickness: '1px', textUnderlineOffset: '3px', backgroundColor: 'var(--color-danger-soft)' },
  '.cm-gutter-lint': { width: '1rem' },
  '.cm-lint-marker': { width: '0.75rem', height: '0.75rem' },
  '.cm-lint-marker-error': { content: 'none', borderRadius: '999px', backgroundColor: 'var(--destructive)' },
  '.cm-tooltip': { border: '1px solid var(--border)', backgroundColor: 'var(--popover)', color: 'var(--popover-foreground)', borderRadius: '0.5rem', boxShadow: 'var(--shadow-pop)' },
  '.cm-tooltip-lint': { padding: '0.25rem 0' },
  '.cm-diagnostic': { padding: '0.25rem 0.75rem', fontFamily: 'var(--font-family-sans)', fontSize: '0.8125rem', maxWidth: '28rem' },
  '.cm-diagnostic-error': { borderLeft: '3px solid var(--destructive)' },
  '.cm-panels': { backgroundColor: 'var(--muted)', color: 'var(--foreground)', fontFamily: 'var(--font-family-sans)' },
  '.cm-panels.cm-panels-top': { borderBottom: '1px solid var(--border)' },
  '.cm-search': { padding: '0.5rem', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.375rem', fontSize: '0.8125rem' },
  '.cm-search label': { display: 'inline-flex', alignItems: 'center', gap: '0.25rem' },
  '.cm-textfield': { minHeight: '2rem', borderRadius: '0.375rem', border: '1px solid var(--input)', backgroundColor: 'var(--card)', color: 'var(--foreground)', padding: '0 0.5rem' },
  '.cm-button': { minHeight: '2rem', borderRadius: '0.375rem', border: '1px solid var(--border)', backgroundImage: 'none', backgroundColor: 'var(--card)', color: 'var(--foreground)', padding: '0 0.625rem' },
  '.cm-panel.cm-search [name=close]': { minWidth: '2rem', minHeight: '2rem', fontSize: '1.25rem', color: 'var(--muted-foreground)' },
})
