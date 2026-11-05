import { cloneElement, useId, type ReactElement, type ReactNode } from 'react'
import { Label } from './label'

interface FieldProps {
  label: ReactNode
  /** Guidance that always shows, such as a password rule. */
  hint?: ReactNode
  /** What is wrong with the value; replaces the hint and marks the control invalid. */
  error?: string | null
  /** One input; the field gives it its id, invalid state and description. */
  children: ReactElement<{ id?: string; 'aria-invalid'?: boolean; 'aria-describedby'?: string }>
}

/** A form control with its label, its hint and its error, wired for screen readers. */
export function Field({ label, hint, error, children }: FieldProps) {
  const id = useId()
  const noteId = `${id}-note`
  const note = error || hint
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {cloneElement(children, { id, 'aria-invalid': error ? true : undefined, 'aria-describedby': note ? noteId : undefined })}
      {note && (
        <p id={noteId} className={error ? 'text-xs text-destructive' : 'text-xs text-muted-foreground'} role={error ? 'alert' : undefined}>
          {note}
        </p>
      )}
    </div>
  )
}
