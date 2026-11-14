import { CloudOff } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { useErrorReason } from '@/shared/lib/error-reason'
import { Button } from './button'
import { StateBlock } from './state-block'

/** A failed request, said in the reader's language: what went wrong by the refusal's code, else by its kind. */
export function ErrorState({ error, title, onRetry, framed, className }: { error: unknown; title: string; onRetry?: () => void; framed?: boolean; className?: string }) {
  const { t } = useTranslation()
  const reason = useErrorReason()
  return (
    <StateBlock
      icon={CloudOff}
      tone="danger"
      title={title}
      description={reason(error)}
      framed={framed}
      className={className}
      action={
        onRetry && (
          <Button type="button" variant="outline" size="sm" onClick={onRetry}>
            {t('errors.retry')}
          </Button>
        )
      }
    />
  )
}
