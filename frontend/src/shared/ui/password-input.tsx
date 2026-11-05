import { Eye, EyeOff } from 'lucide-react'
import { useState, type ComponentProps } from 'react'
import { cn } from '@/shared/lib/utils'
import { Input } from './input'

interface PasswordInputProps extends Omit<ComponentProps<'input'>, 'type'> {
  showLabel: string
  hideLabel: string
}

/** A password input that can show what was typed, which matters on a phone keyboard. */
export function PasswordInput({ showLabel, hideLabel, className, ...props }: PasswordInputProps) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="relative">
      <Input {...props} type={visible ? 'text' : 'password'} spellCheck={false} className={cn('pr-12 md:pr-10', className)} />
      <button
        type="button"
        onClick={() => setVisible(!visible)}
        aria-label={visible ? hideLabel : showLabel}
        aria-pressed={visible}
        className="absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-lg text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:w-9"
      >
        {visible ? <EyeOff aria-hidden className="size-4" /> : <Eye aria-hidden className="size-4" />}
      </button>
    </div>
  )
}
