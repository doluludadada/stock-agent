import { CloudOff } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { Button } from './button'
import { StateBlock } from './state-block'

/** A failed request, said in the user's terms: what went wrong by kind, with the server's own reason when it gave one. */
export function ErrorState({ error, title, onRetry, className }: { error: unknown; title: string; onRetry?: () => void; className?: string }) {
  const { t } = useTranslation()
  const kind = isApiError(error) ? error.kind : 'server'
  const detail = isApiError(error) && (kind === 'forbidden' || kind === 'invalid' || kind === 'notFound') ? error.message : ''
  return (
    <StateBlock
      icon={CloudOff}
      tone="danger"
      title={title}
      description={[t(`errors.${kind}`), detail].filter(Boolean).join(' ')}
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
