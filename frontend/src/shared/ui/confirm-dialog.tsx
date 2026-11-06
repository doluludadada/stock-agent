import type { ReactNode } from 'react'
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
  /** For a dialog whose `open` follows outside state, such as a navigation blocker, instead of `onOpenChange`. */
  onCancel?: () => void
  destructive?: boolean
}

/** A question that needs an explicit yes before something costly or irreversible happens. */
export function ConfirmDialog({ open, onOpenChange, title, description, children, cancel, confirm, onConfirm, onCancel, destructive = false }: ConfirmDialogProps) {
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
          <AlertDialogAction variant={destructive ? 'destructive' : 'default'} onClick={onConfirm}>
            {confirm}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
