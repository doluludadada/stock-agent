import { ChevronDown, CornerDownRight } from 'lucide-react'
import { useId, useState } from 'react'
import { useTranslation } from '@/i18n'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { parseDiff, sortProblems, type SettingsEdit, type SettingsFileId, type SettingsProblem } from './model'

/** Puts the caret on a 1-based line and column of the open file. */
export type Reveal = (line: number, column: number) => void

/**
 * Each problem the server found, where it is and what is wrong, in reading order. A problem in the open file is a
 * button that puts the caret on it; one in the other file, or from .env or the database, only says where it is.
 */
export function ProblemList({ problems, file, onReveal }: { problems: readonly SettingsProblem[]; file: SettingsFileId; onReveal?: Reveal }) {
  const { t } = useTranslation('admin')
  return (
    <ol className="-mx-1.5 space-y-0.5">
      {sortProblems(problems, file).map((problem, index) => {
        const place =
          problem.file && problem.line
            ? problem.file === file
              ? t('problem.here', { line: problem.line, column: problem.column ?? 1 })
              : t('problem.elsewhere', { file: t(`file.${problem.file}`), line: problem.line, column: problem.column ?? 1 })
            : t('problem.nowhere')
        const body = (
          <>
            <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="tabular text-xs font-medium text-destructive">{place}</span>
              {problem.path && <code className="font-mono text-xs break-all text-muted-foreground">{problem.path}</code>}
            </span>
            <span className="block text-sm text-pretty break-words">{problem.message}</span>
          </>
        )
        const line = problem.file === file ? problem.line : null
        return (
          <li key={`${index}-${problem.path}-${problem.line}`}>
            {onReveal && line ? (
              <button
                type="button"
                onClick={() => onReveal(line, problem.column ?? 1)}
                className="group flex min-h-11 w-full items-start gap-2 rounded-lg px-1.5 py-1.5 text-left transition-colors hover:bg-danger-soft focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <CornerDownRight aria-hidden className="mt-0.5 size-4 shrink-0 text-destructive" />
                <span className="min-w-0">{body}</span>
              </button>
            ) : (
              <div className="flex items-start gap-2 px-1.5 py-1.5">
                <span aria-hidden className="mt-1.5 size-2 shrink-0 rounded-full bg-destructive" />
                <span className="min-w-0">{body}</span>
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}

/** The settings a save or a restore changes, as the server worked them out from the two texts. */
export function ChangeSummary({ edit }: { edit: SettingsEdit }) {
  const { t } = useTranslation('admin')
  if (edit.changed.length === 0) return <p className="text-sm text-muted-foreground">{t('changes.none')}</p>
  return (
    <div className="space-y-1.5">
      <p className="eyebrow">{t('changes.title', { count: edit.changed.length })}</p>
      <ul className="divide-y rounded-lg border">
        {edit.changed.map((path) => (
          <li key={path} className="px-3 py-2">
            <code className="font-mono text-xs break-all">{path}</code>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * The server's line diff, numbered on both sides. With `onRevealLine`, a line of the new text is a button that shows
 * it in the editor; the diff of a restore has none, since the editor does not hold the version being restored.
 */
export function LineChanges({ diff, defaultOpen = false, onRevealLine }: { diff: readonly string[]; defaultOpen?: boolean; onRevealLine?: (line: number) => void }) {
  const { t } = useTranslation('admin')
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()
  const rows = parseDiff(diff)
  if (rows.length === 0) return null
  const counted = rows.filter((row) => row.kind === 'added' || row.kind === 'removed').length
  return (
    <div className="space-y-2">
      <Button type="button" variant="ghost" size="sm" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)} className="-ml-2.5">
        <ChevronDown aria-hidden className={cn('transition-transform', !open && '-rotate-90')} />
        {open ? t('changes.hideLines') : t('changes.lines')}
        <span className="tabular text-xs font-normal text-muted-foreground">{counted}</span>
      </Button>
      {open && (
        <div id={id} className="max-h-96 overflow-auto overscroll-contain rounded-lg border bg-card font-mono text-xs leading-relaxed">
          <table className="w-full border-collapse">
            <tbody>
              {rows.map((row, index) =>
                row.kind === 'hunk' ? (
                  <tr key={index} className="bg-muted text-muted-foreground">
                    <td colSpan={3} className="px-2 py-1">
                      {onRevealLine ? (
                        <button type="button" onClick={() => onRevealLine(row.newStart)} className="tabular min-h-8 text-left underline-offset-2 hover:text-foreground hover:underline">
                          {t('changes.showLine', { line: row.newStart })}
                        </button>
                      ) : (
                        <span className="tabular">{t('changes.from', { line: row.oldStart })}</span>
                      )}
                    </td>
                  </tr>
                ) : (
                  <tr key={index} className={cn(row.kind === 'added' && 'bg-brand-soft', row.kind === 'removed' && 'bg-muted text-muted-foreground')}>
                    <td className="tabular w-px border-r px-1.5 text-right align-top whitespace-nowrap text-faint select-none">{row.oldLine ?? ''}</td>
                    <td className="tabular w-px border-r px-1.5 text-right align-top whitespace-nowrap text-faint select-none">{row.newLine ?? ''}</td>
                    <td className="px-2 align-top break-all whitespace-pre-wrap">
                      <span className={cn('mr-1.5 inline-block w-2 select-none', row.kind === 'added' && 'text-brand')}>{row.kind === 'added' ? '+' : row.kind === 'removed' ? '−' : ' '}</span>
                      {row.text}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
