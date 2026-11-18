import { ArrowRight } from 'lucide-react'
import { useId, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { isApiError, useHasPermission, useSession, useShows, type Schemas } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useErrorReason } from '@/shared/lib/error-reason'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { Label } from '@/shared/ui/label'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { PreferenceControls } from '@/shared/ui/preference-controls'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { useAiModels, useChooseAiModel, type AiModels, type AiProvider } from './api'

interface MySettingsPageProps {
  /** The accounts' panels: the mock account's starting capital and reset, and the ranking follow's account and schedule. */
  accountPanels?: ReactNode
}

/**
 * Everything that is the signed-in user's own: who they are and how their password changes, the language and the
 * theme, the AI model of their runs, their mock account, and where their active strategy is chosen.
 */
export function MySettingsPage({ accountPanels }: MySettingsPageProps) {
  const { t } = useTranslation('auth')
  const library = useShows('strategy_library')
  const session = useSession()
  return (
    <div className="page-stack">
      <PageHeader title={t('settings.title')} />
      <RequireSignIn layout="page" reason={t('settings.signIn')}>
        <div className="card-grid max-w-3xl">
          {session.status === 'signedIn' && <AccountPanel user={session.user} />}
          <DisplayPanel />
          <AiModelPanel />
          {accountPanels}
          {library && (
            <Panel title={t('settings.strategy.title')}>
              <Button asChild variant="outline" size="sm">
                <Link to={paths.strategies}>
                  {t('settings.strategy.link')}
                  <ArrowRight aria-hidden />
                </Link>
              </Button>
            </Panel>
          )}
        </div>
      </RequireSignIn>
    </div>
  )
}

/** Who is signed in, and the one way this site changes their password: an administrator sets a new one on the users page. */
function AccountPanel({ user }: { user: Schemas['User'] }) {
  const { t } = useTranslation('auth')
  const managesUsers = useHasPermission('manage_users')
  return (
    <Panel title={t('settings.account.title')}>
      <div className="space-y-3">
        <dl className="grid grid-cols-1 gap-4 @md:grid-cols-3">
          <Stat label={t('settings.account.username')}>{user.username}</Stat>
          <Stat label={t('settings.account.email')}>
            <span className="break-all">{user.email}</span>
          </Stat>
          <Stat label={t('settings.account.role')}>{t(`role.${user.role}`)}</Stat>
        </dl>
        <p className="text-sm text-pretty text-muted-foreground">
          {!user.has_password ? t('settings.account.google') : managesUsers ? t('settings.account.passwordOwn') : t('settings.account.passwordAsk')}
          {user.has_password && managesUsers && (
            <>
              {' '}
              <Link to={paths.users} className="tap font-medium text-brand underline-offset-4 hover:underline">
                {t('settings.account.users')}
              </Link>
            </>
          )}
        </p>
      </div>
    </Panel>
  )
}

/** The language and the theme, which this browser keeps: the same two choices as the header's menus. */
function DisplayPanel() {
  const { t } = useTranslation('auth')
  return (
    <Panel title={t('common:preferences.title')}>
      <PreferenceControls labelled />
      <p className="mt-3 text-xs text-muted-foreground">{t('common:preferences.kept')}</p>
    </Panel>
  )
}

function AiModelPanel() {
  const { t } = useTranslation('auth')
  const models = useAiModels()
  return (
    <Panel title={t('settings.aiModel.title')}>
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
  const reason = useErrorReason()
  const providers = Object.keys(offer.models) as AiProvider[]
  const name = (provider: AiProvider) => t('settings.aiModel.option', { provider: t(`settings.provider.${provider}`), model: offer.models[provider] })
  const shown = choose.isPending ? (choose.variables ?? offer.site_default) : offer.in_use
  const status = (): string => {
    if (choose.isPending) return t('settings.aiModel.saving')
    if (choose.isSuccess) return t('settings.aiModel.saved', { name: name(choose.data.in_use) })
    if (isApiError(choose.error) && choose.error.code === 'ai_model_not_offered') return t('settings.aiModel.notOffered')
    if (choose.isError) return t('settings.aiModel.failed', { reason: reason(choose.error) })
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
