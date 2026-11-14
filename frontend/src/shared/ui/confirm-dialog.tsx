import { useEffect, useRef, type ReactNode } from 'react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from './alert-dialog'

interface ConfirmDialogProps {
  open: boolean
  onOpenChange?: (open: boolean) => void
  title: ReactNode
  description: ReactNode
  /** What the yes covers in detail, such as a list, under the description, which is one paragraph. */
  children?: ReactNode
  cancel: string
  confirm: string
  onConfirm: () => void
  /** While the yes cannot be given yet, such as before a required field holds a valid value. */
  confirmDisabled?: boolean
  /** For a dialog whose `open` follows outside state, such as a navigation blocker, instead of `onOpenChange`. */
  onCancel?: () => void
  destructive?: boolean
}

/** A question that needs an explicit yes before something costly or irreversible happens. */
export function ConfirmDialog({ open, onOpenChange, title, description, children, cancel, confirm, onConfirm, confirmDisabled = false, onCancel, destructive = false }: ConfirmDialogProps) {
  // The dialog takes a moment to close, and a second press in that moment must not confirm twice.
  const answered = useRef(false)
  useEffect(() => {
    if (open) answered.current = false
  }, [open])
  const confirmOnce = () => {
    if (answered.current) return
    answered.current = true
    onConfirm()
  }
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {children}
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>{cancel}</AlertDialogCancel>
          <AlertDialogAction variant={destructive ? 'destructive' : 'default'} disabled={confirmDisabled} onClick={confirmOnce}>
            {confirm}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
