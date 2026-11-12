import { LoaderCircle } from 'lucide-react'
import { useEffect, useState } from 'react'

interface ProgressNoteProps {
  /** When the wait began, in epoch milliseconds. */
  since: number
  /** The headline for the seconds waited so far. */
  title: (seconds: number) => string
  /** Why it takes this long, and what the reader may do meanwhile. */
  hint: string
}

/** A wait of seconds to tens of seconds, said honestly: the seconds so far and why it is slow. */
export function ProgressNote({ since, title, hint }: ProgressNoteProps) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const seconds = Math.max(0, Math.floor((now - since) / 1000))
  return (
    <output className="flex items-start gap-3 rounded-2xl border border-primary/30 bg-brand-soft px-4 py-3.5 text-sm">
      <LoaderCircle aria-hidden className="mt-0.5 size-4 shrink-0 animate-spin text-brand motion-reduce:animate-none" />
      <div className="min-w-0 space-y-0.5">
        <p className="font-medium">{title(seconds)}</p>
        <p className="text-pretty text-muted-foreground">{hint}</p>
      </div>
    </output>
  )
}
