import { ArrowRight, FlaskConical, Landmark, TriangleAlert } from 'lucide-react'
import { useState, type ComponentType, type ReactNode } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { useHasPermission, useShows, type PageRefusal, type SaveConfirmationProps, type Schemas } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { Field } from '@/shared/ui/field'
import { Input } from '@/shared/ui/input'
import { Panel } from '@/shared/ui/panel'
import type { BrokerageAccount } from './api'
import { loginState } from './model'

type SettingChange = Schemas['SettingChange']
type Server = BrokerageAccount['server']

type Action = 'server' | 'ordering' | 'cash'

/**
 * The SinoPac account's name, its server and its login first, before any figure. For an administrator who edits the
 * settings it is also where SinoPac is managed: the server, ordering on it, and the simulation account's starting cash,
 * each a settings save behind the administrator's password. The server decides every rule of a switch.
 */
export function SinoPacPanel({ account, Confirmation }: { account: BrokerageAccount; Confirmation: ComponentType<SaveConfirmationProps> }) {
  const { t } = useTranslation('account')
  const format = useFormat()
  const analysed = useShows('holdings')
  const manages = useHasPermission('edit_system_settings')
  const Icon = account.server === 'simulation' ? FlaskConical : Landmark
  return (
    <Panel>
      <div className="space-y-3">
        <p className="flex flex-wrap items-center gap-x-3 gap-y-2 text-title font-semibold">
          <span className="flex items-center gap-2">
            <Icon aria-hidden className="size-4.5 shrink-0 text-gold" />
            {t('brokerage.account')}
          </span>
          <Badge variant="outline" className={cn('font-normal', account.server === 'production' ? 'border-destructive/50 text-destructive' : 'text-muted-foreground')}>
            {t(`brokerage.server.${account.server}`)}
          </Badge>
          <Badge variant="outline" className="font-normal text-muted-foreground">
            {t(`brokerage.login.${loginState(account)}`)}
          </Badge>
          <Badge variant="outline" className={cn('font-normal', account.ordering ? 'border-gold/50 text-gold' : 'text-muted-foreground')}>
            {t(account.ordering ? 'brokerage.ordering.on' : 'brokerage.ordering.off')}
          </Badge>
        </p>
        <p className="text-sm text-pretty text-muted-foreground">{t(`brokerage.serverNote.${account.server}`)}</p>
        {account.statement && (
          <p className="flex flex-wrap items-center gap-x-3 text-xs text-pretty text-muted-foreground">
            {t('brokerage.own', { time: format.dateTime(account.statement.read_at) })}
            {analysed && (
              <Link to={paths.holdings} className="inline-flex min-h-11 items-center gap-1 text-brand underline-offset-4 hover:underline md:min-h-0">
                {t('brokerage.analysis')}
                <ArrowRight aria-hidden className="size-3.5" />
              </Link>
            )}
          </p>
        )}
        {manages && <Manage account={account} Confirmation={Confirmation} />}
      </div>
    </Panel>
  )
}

function Manage({ account, Confirmation }: { account: BrokerageAccount; Confirmation: ComponentType<SaveConfirmationProps> }) {
  const { t } = useTranslation('account')
  const format = useFormat()
  const [action, setAction] = useState<Action | null>(null)
  const [refused, setRefused] = useState<{ text: string; serverSwitch: boolean } | null>(null)
  const target: Server = account.server === 'simulation' ? 'production' : 'simulation'
  const switchRefusal = account.switch_refusal
  const cash = account.simulation_initial_cash

  const open = (next: Action) => {
    setRefused(null)
    setAction(next)
  }
  const refuse = (refusal: PageRefusal) => {
    setAction(null)
    setRefused({ text: refusalText(refusal, t), serverSwitch: action === 'server' })
  }

  return (
    <div className="divide-y divide-dashed border-t pt-1">
      <Row label={t('brokerage.manage.server.label')} value={t(`brokerage.server.${account.server}`)}>
        <Button type="button" variant="outline" disabled={switchRefusal !== null} onClick={() => open('server')}>
          {t(`brokerage.manage.server.to.${target}`)}
        </Button>
      </Row>
      {switchRefusal && (
        <div className="py-3 text-sm text-pretty text-muted-foreground">
          <p>
            {t(`brokerage.manage.server.refusal.${switchRefusal.reason}`, {
              server: t(`brokerage.server.${switchRefusal.server}`),
              count: switchRefusal.unsettled,
            })}
          </p>
          {switchRefusal.missing.length > 0 && (
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {switchRefusal.missing.map((variable) => (
                <li key={variable}>
                  <code className="rounded bg-muted px-1.5 py-0.5 text-xs text-foreground">{variable}</code>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <Row label={t('brokerage.manage.ordering.label')} value={t(account.ordering ? 'brokerage.ordering.on' : 'brokerage.ordering.off')}>
        <Button type="button" variant="outline" onClick={() => open('ordering')}>
          {t(account.ordering ? 'brokerage.manage.ordering.turnOff' : 'brokerage.manage.ordering.turnOn')}
        </Button>
      </Row>
      {cash !== null && (
        <Row label={t('brokerage.manage.cash.label')} value={format.number(cash)} note={t('brokerage.manage.cash.note')}>
          <Button type="button" variant="outline" onClick={() => open('cash')}>
            {t('brokerage.manage.cash.edit')}
          </Button>
        </Row>
      )}
      {refused && (
        <p role="alert" className="flex items-start gap-2 py-3 text-sm text-destructive">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
          <span>
            {refused.text}
            {/* Only the account read again after the refusal says whether the save's turn-off, written first, went through. */}
            {refused.serverSwitch && !account.ordering && ` ${t('brokerage.manage.refused.orderingOff')}`}
          </span>
        </p>
      )}
      {action === 'server' && <ServerSwitch target={target} Confirmation={Confirmation} onClose={() => setAction(null)} onRefused={refuse} />}
      {action === 'ordering' && <OrderingSwitch account={account} Confirmation={Confirmation} onClose={() => setAction(null)} onRefused={refuse} />}
      {action === 'cash' && cash !== null && <CashChange cash={cash} Confirmation={Confirmation} onClose={() => setAction(null)} onRefused={refuse} />}
    </div>
  )
}

function Row({ label, value, note, children }: { label: string; value: string; note?: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
      <div className="min-w-0">
        <p className="text-sm">
          <span className="text-muted-foreground">{label}</span> <span className="font-medium">{value}</span>
        </p>
        {note && <p className="text-xs text-pretty text-muted-foreground">{note}</p>}
      </div>
      {children}
    </div>
  )
}

interface SaveProps {
  Confirmation: ComponentType<SaveConfirmationProps>
  onClose: () => void
  onRefused: (refusal: PageRefusal) => void
}

/** The server's switch: what changes, and on the way to production the server's name typed out, then the password. */
function ServerSwitch({ target, Confirmation, onClose, onRefused }: SaveProps & { target: Server }) {
  const { t } = useTranslation('account')
  const [typed, setTyped] = useState('')
  const phrase = t('brokerage.server.production')
  const changes: SettingChange[] = [
    { path: 'shioaji.server', value: target },
    { path: 'features.sinopac_ordering', value: 'off' },
  ]
  const consequences = target === 'production' ? (['realMoney', 'orderingOff', 'login', 'follows'] as const) : (['noRealMoney', 'orderingOff', 'login'] as const)
  return (
    <Confirmation
      open
      onOpenChange={(open) => !open && onClose()}
      changes={changes}
      title={t(`brokerage.manage.server.title.${target}`)}
      description={t('brokerage.manage.server.description')}
      ready={target === 'simulation' || typed.trim() === phrase}
      returnTo={paths.brokerage}
      onSaved={() => {
        onClose()
        toast.success(t('brokerage.manage.server.saved', { server: t(`brokerage.server.${target}`) }))
      }}
      onRefused={onRefused}
    >
      <ul className="list-disc space-y-1 pl-5 text-sm text-pretty">
        {consequences.map((consequence) => (
          <li key={consequence}>{t(`brokerage.manage.server.changes.${consequence}`)}</li>
        ))}
      </ul>
      {target === 'production' && (
        <Field label={t('brokerage.manage.server.type', { phrase })}>
          <Input value={typed} onChange={(event) => setTyped(event.target.value)} autoComplete="off" />
        </Field>
      )}
    </Confirmation>
  )
}

/** Ordering on SinoPac between off and administrators, the same save and the same confirmation. */
function OrderingSwitch({ account, Confirmation, onClose, onRefused }: SaveProps & { account: BrokerageAccount }) {
  const { t } = useTranslation('account')
  const next = account.ordering ? 'off' : 'on'
  return (
    <Confirmation
      open
      onOpenChange={(open) => !open && onClose()}
      changes={[{ path: 'features.sinopac_ordering', value: account.ordering ? 'off' : 'administrators' }]}
      title={t(`brokerage.manage.ordering.title.${next}`)}
      description={t(`brokerage.manage.ordering.description.${next}`)}
      returnTo={paths.brokerage}
      onSaved={() => {
        onClose()
        toast.success(t(`brokerage.manage.ordering.saved.${next}`))
      }}
      onRefused={onRefused}
    >
      {next === 'on' && account.server === 'production' && <p className="text-sm font-medium text-destructive">{t('brokerage.manage.ordering.realMoney')}</p>}
    </Confirmation>
  )
}

/** The simulation account's starting cash: what the owner has put in, so adding money is raising it. */
function CashChange({ cash, Confirmation, onClose, onRefused }: SaveProps & { cash: number }) {
  const { t } = useTranslation('account')
  const format = useFormat()
  const [typed, setTyped] = useState(String(cash))
  const amount = Number(typed)
  const valid = typed.trim() !== '' && Number.isFinite(amount) && amount > 0
  return (
    <Confirmation
      open
      onOpenChange={(open) => !open && onClose()}
      changes={valid ? [{ path: 'shioaji.simulation_initial_cash', value: amount }] : []}
      title={t('brokerage.manage.cash.title')}
      description={t('brokerage.manage.cash.note')}
      ready={valid && amount !== cash}
      returnTo={paths.brokerage}
      onSaved={() => {
        onClose()
        toast.success(t('brokerage.manage.cash.saved', { amount: format.number(amount) }))
      }}
      onRefused={onRefused}
    >
      <Field label={t('brokerage.manage.cash.field')} error={typed.trim() !== '' && !valid ? t('brokerage.manage.cash.invalid') : null}>
        <Input value={typed} onChange={(event) => setTyped(event.target.value)} inputMode="numeric" autoComplete="off" />
      </Field>
    </Confirmation>
  )
}

/** What a refused save says here; why a switch of the server is refused, the account read again says beside its button. */
function refusalText(refusal: PageRefusal, t: (key: string) => string): string {
  return t(refusal.kind === 'conflict' ? 'brokerage.manage.refused.conflict' : 'brokerage.manage.refused.other')
}
