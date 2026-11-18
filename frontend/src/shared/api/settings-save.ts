import type { ReactNode } from 'react'
import type { components } from './schema.gen'

type Schemas = components['schemas']

/** A refusal of the settings themselves, or another save first: the dialog closes, and the page says it. */
export type PageRefusal = { kind: 'refused'; problems: Schemas['SettingsProblem'][]; error: unknown } | { kind: 'conflict' }

/**
 * The props of the settings save's one confirmation, which every page that saves a setting uses: the settings page,
 * and the SinoPac account page, which the route hands it to.
 */
export interface SaveConfirmationProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  changes: Schemas['SettingChange'][]
  onSaved: () => void
  onRefused: (refusal: PageRefusal) => void
  /** A page's own title and sentence, in place of the settings page's. */
  title?: string
  description?: string
  /** What the dialog shows before it asks: what the save changes, and a field of the page's own. */
  children?: ReactNode
  /** False holds the confirmation until the page's own field is filled. */
  ready?: boolean
  /**
   * The page the save is made on when it is not the settings page. Google sends the browser back to the settings
   * page, which sends the save and then goes back here.
   */
  returnTo?: string
  /** Called right before the browser leaves for Google, so the page lets it go without asking. */
  onLeave?: () => void
}
