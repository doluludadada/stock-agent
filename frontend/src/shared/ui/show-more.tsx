import { ChevronDown } from 'lucide-react'
import { cn } from '@/shared/lib/utils'
import { Button } from './button'

interface ShowMoreProps {
  expanded: boolean
  onToggle: () => void
  /** The id of the list it opens. */
  controls: string
  moreLabel: string
  lessLabel: string
}

/** The footer toggle of a card whose list shows its first rows until asked for the rest. */
export function ShowMore({ expanded, onToggle, controls, moreLabel, lessLabel }: ShowMoreProps) {
  return (
    <Button type="button" variant="ghost" size="sm" className="w-full text-muted-foreground" aria-expanded={expanded} aria-controls={controls} onClick={onToggle}>
      {expanded ? lessLabel : moreLabel}
      <ChevronDown aria-hidden className={cn('transition-transform', expanded && 'rotate-180')} />
    </Button>
  )
}
