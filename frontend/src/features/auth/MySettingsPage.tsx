import { ArrowRight } from 'lucide-react'
import { useId } from 'react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { Label } from '@/shared/ui/label'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { Skeleton } from '@/shared/ui/skeleton'
import { useAiModels, useChooseAiModel, type AiModels, type AiProvider } from './api'

/** The signed-in user's own settings: the AI model of their runs, and where their active strategy is chosen. */
export function MySettingsPage() {
  const { t } = useTranslation('auth')
  return (
    <div className="space-y-5 lg:space-y-6">
      <PageHeader eyebrow={t('common:nav.section.mine')} title={t('settings.title')} description={t('settings.description')} />
      <RequireSignIn layout="page" reason={t('settings.signIn')}>
        <div className="grid max-w-3xl gap-4 lg:gap-5">
          <AiModelPanel />
          <Panel title={t('settings.strategy.title')} description={t('settings.strategy.description')}>
            <Button asChild variant="outline" size="sm">
              <Link to={paths.strategies}>
                {t('settings.strategy.link')}
                <ArrowRight aria-hidden />
              </Link>
            </Button>
          </Panel>
        </div>
      </RequireSignIn>
    </div>
  )
}

function AiModelPanel() {
  const { t } = useTranslation('auth')
  const models = useAiModels()
  return (
    <Panel title={t('settings.aiModel.title')} description={t('settings.aiModel.description')}>
      {models.isPending ? (
        <Skeleton className="h-16 rounded-xl" />
      ) : models.isError ? (
        <ErrorState error={models.error} title={t('settings.aiModel.loadFailed')} onRetry={() => void models.refetch()} />
      ) : (
        <AiModelSelect offer={models.data} />
      )}
    </Panel>
  )
}

/** Saves on every pick; the site's default is saved as no choice, so the user follows the administrator's later changes. */
function AiModelSelect({ offer }: { offer: AiModels }) {
  const { t } = useTranslation('auth')
  const id = useId()
  const choose = useChooseAiModel()
  const providers = Object.keys(offer.models) as AiProvider[]
  const name = (provider: AiProvider) => t('settings.aiModel.option', { provider: t(`settings.provider.${provider}`), model: offer.models[provider] })
  const shown = choose.isPending ? (choose.variables ?? offer.site_default) : offer.in_use
  const status = (): string => {
    if (choose.isPending) return t('settings.aiModel.saving')
    if (choose.isSuccess) return t('settings.aiModel.saved', { name: name(choose.data.in_use) })
    if (isApiError(choose.error) && choose.error.code === 'ai_model_not_offered') return t('settings.aiModel.notOffered')
    if (choose.isError) return t('settings.aiModel.failed', { reason: isApiError(choose.error) ? t(`common:errors.${choose.error.kind}`) : '' })
    return providers.length < 2 ? t('settings.aiModel.onlyDefault') : t('settings.aiModel.hint')
  }
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{t('settings.aiModel.label')}</Label>
      <Select
        value={shown}
        onValueChange={(value) => choose.mutate(value === offer.site_default ? null : (value as AiProvider))}
        disabled={choose.isPending || providers.length < 2}
      >
        <SelectTrigger id={id} aria-describedby={`${id}-status`} className="w-full @md:w-96">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {providers.map((provider) => (
            <SelectItem key={provider} value={provider}>
              {provider === offer.site_default ? t('settings.aiModel.siteDefault', { name: name(provider) }) : name(provider)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p id={`${id}-status`} aria-live="polite" className={choose.isError ? 'text-xs text-destructive' : 'text-xs text-muted-foreground'}>
        {status()}
      </p>
    </div>
  )
}
