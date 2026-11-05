import { Ellipsis, Search, UsersRound } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { isApiError, useSession, type User } from '@/shared/api'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/shared/ui/alert-dialog'
import { Avatar } from '@/shared/ui/avatar'
import { Button } from '@/shared/ui/button'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shared/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/shared/ui/dropdown-menu'
import { ErrorState } from '@/shared/ui/error-state'
import { Field } from '@/shared/ui/field'
import { Input } from '@/shared/ui/input'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { PasswordInput } from '@/shared/ui/password-input'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Segmented } from '@/shared/ui/segmented'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { useChangeUser, useSignOut, useUsers } from './api'
import { changeBody, changeKey, changeOptions, passwordProblem, type UserChange } from './model'
import { RoleBadge } from './UserMenu'

type Filter = 'all' | 'administrator' | 'user' | 'deactivated'

const FILTERS: Record<Filter, (user: User) => boolean> = {
  all: () => true,
  administrator: (user) => user.role === 'administrator' && user.status === 'active',
  user: (user) => user.role === 'user' && user.status === 'active',
  deactivated: (user) => user.status === 'deactivated',
}

/** The administrator's directory of accounts: who they are, their role, whether they can sign in. */
export function UsersPage() {
  const { t } = useTranslation('auth')
  const users = useUsers()
  const list = users.data ?? []
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow={t('users.eyebrow')}
        title={t('users.title')}
        description={
          users.data
            ? t('users.summary', { count: list.length, admins: list.filter(FILTERS.administrator).length, deactivated: list.filter(FILTERS.deactivated).length })
            : t('users.description')
        }
      />
      <RequireSignIn needs="manage_users" layout="page" reason={t('users.signIn')}>
        <div className="grid items-start gap-4 lg:gap-5 xl:grid-cols-12">
          <div className="min-w-0 xl:col-span-8">
            {users.isPending ? (
              <Skeleton className="h-72 rounded-2xl" />
            ) : users.isError ? (
              <ErrorState error={users.error} title={t('users.loadFailed')} onRetry={() => void users.refetch()} className="rounded-2xl border bg-card" />
            ) : (
              <UserList users={list} />
            )}
          </div>
          <RolesPanel />
        </div>
      </RequireSignIn>
    </div>
  )
}

interface Asking {
  user: User
  change: UserChange
}

function UserList({ users }: { users: User[] }) {
  const { t } = useTranslation('auth')
  const format = useFormat()
  const current = useSession()
  const actorId = current.status === 'signedIn' ? current.user.user_id : ''
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [asking, setAsking] = useState<Asking | null>(null)
  const change = useChangeUser()
  const signOut = useSignOut()
  const needle = query.trim().toLowerCase()
  const shown = useMemo(
    () => users.filter((user) => FILTERS[filter](user) && (!needle || user.username.toLowerCase().includes(needle) || user.email.toLowerCase().includes(needle))),
    [users, filter, needle],
  )

  /** Rejects when the server refused, after the toast said why; the password dialog stays open on it. */
  const apply = ({ user, change: wanted }: Asking, password = '') =>
    change.mutateAsync(
      { userId: user.user_id, body: changeBody(wanted, password) },
      {
        onSuccess: () => {
          if (wanted.kind === 'password' && user.user_id === actorId) {
            toast.success(t('users.done.ownPassword'))
            signOut.mutate()
            return
          }
          toast.success(t(`users.done.${changeKey(wanted)}`, { name: user.username }))
        },
        onError: (error) =>
          toast.error(
            isApiError(error) && error.code === 'last_administrator'
              ? t('users.lastAdministrator')
              : t('users.failed', { reason: isApiError(error) ? t(`common:errors.${error.kind}`) : '' }),
          ),
      },
    )

  const columns: Column<User>[] = [
    {
      key: 'user',
      header: t('users.column.user'),
      cell: (user) => (
        <div className="flex min-w-0 items-center gap-3 py-1">
          <Avatar name={user.username} className={cn(user.status === 'deactivated' && 'bg-muted text-muted-foreground')} />
          <div className="min-w-0">
            <p className="flex items-center gap-2 font-medium">
              <span className={cn('truncate', user.status === 'deactivated' && 'text-muted-foreground')}>{user.username}</span>
              {user.user_id === actorId && <span className="rounded-full border px-1.5 text-xs font-normal text-muted-foreground">{t('users.you')}</span>}
            </p>
            <p className="truncate text-xs text-muted-foreground">{user.email}</p>
            <p className="mt-1.5 flex flex-wrap items-center gap-2 md:hidden">
              <RoleBadge kind={user.role} />
              <Status user={user} />
            </p>
          </div>
        </div>
      ),
      className: 'w-full max-w-0',
    },
    { key: 'role', header: t('users.column.role'), from: 'md', cell: (user) => <RoleBadge kind={user.role} /> },
    { key: 'status', header: t('users.column.status'), from: 'md', cell: (user) => <Status user={user} /> },
    { key: 'created', header: t('users.column.created'), from: 'lg', cell: (user) => <span className="tabular text-muted-foreground">{format.date(user.created_at)}</span> },
    {
      key: 'actions',
      header: t('users.column.actions'),
      quietHeader: true,
      className: 'w-14 text-right',
      cell: (user) => (
        <RowMenu
          user={user}
          actorId={actorId}
          onPick={(wanted) => (wanted.kind === 'status' && wanted.status === 'active' ? apply({ user, change: wanted }).catch(() => undefined) : setAsking({ user, change: wanted }))}
        />
      ),
    },
  ]

  return (
    <Panel flush title={t('users.list.title')} description={t('users.list.count', { count: shown.length, total: users.length })}>
      <div className="flex flex-col gap-2 border-b px-4 py-3 md:px-5 @2xl:flex-row @2xl:items-center">
        <Segmented
          value={filter}
          onChange={setFilter}
          label={t('users.filter.label')}
          options={(Object.keys(FILTERS) as Filter[]).map((key) => ({ value: key, label: t(`users.filter.${key}`), count: users.filter(FILTERS[key]).length }))}
        />
        <span className="relative min-w-0 @2xl:ml-auto @2xl:w-60">
          <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('users.search.placeholder')} aria-label={t('users.search.label')} className="pl-9" />
        </span>
      </div>
      {shown.length === 0 ? (
        <StateBlock icon={UsersRound} title={t('users.noMatch')} description={t('users.noMatchHint')} />
      ) : (
        <DataTable rows={shown} columns={columns} rowKey={(user) => user.user_id} label={t('users.list.title')} />
      )}
      <ConfirmChange asking={asking?.change.kind === 'password' ? null : asking} onClose={() => setAsking(null)} onConfirm={(confirmed) => apply(confirmed).catch(() => undefined)} />
      <NewPasswordDialog
        asking={asking?.change.kind === 'password' ? asking : null}
        isSelf={asking?.user.user_id === actorId}
        onClose={() => setAsking(null)}
        onSave={(confirmed, password) => apply(confirmed, password)}
      />
    </Panel>
  )
}

function RowMenu({ user, actorId, onPick }: { user: User; actorId: string; onPick: (change: UserChange) => void }) {
  const { t } = useTranslation('auth')
  const options = changeOptions(actorId, user)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon" aria-label={t('users.actions', { name: user.username })}>
          <Ellipsis aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        {options.map((option) => (
          <DropdownMenuItem
            key={changeKey(option.change)}
            disabled={option.blocked}
            variant={option.change.kind === 'status' && option.change.status === 'deactivated' ? 'destructive' : 'default'}
            onSelect={() => onPick(option.change)}
          >
            {t(`users.change.${changeKey(option.change)}`)}
          </DropdownMenuItem>
        ))}
        {options.some((option) => option.blocked) && <DropdownMenuLabel className="text-xs font-normal text-pretty text-muted-foreground">{t('users.selfBlocked')}</DropdownMenuLabel>}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ConfirmChange({ asking, onClose, onConfirm }: { asking: Asking | null; onClose: () => void; onConfirm: (asking: Asking) => void }) {
  const { t } = useTranslation('auth')
  const key = asking ? changeKey(asking.change) : null
  return (
    <AlertDialog open={asking !== null} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        {asking && key && (
          <>
            <AlertDialogHeader>
              <AlertDialogTitle>{t(`users.confirm.${key}.title`, { name: asking.user.username })}</AlertDialogTitle>
              <AlertDialogDescription>{t(`users.confirm.${key}.description`, { name: asking.user.username })}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t('users.cancel')}</AlertDialogCancel>
              <AlertDialogAction variant={key === 'deactivate' ? 'destructive' : 'default'} onClick={() => onConfirm(asking)}>
                {t(`users.change.${key}`)}
              </AlertDialogAction>
            </AlertDialogFooter>
          </>
        )}
      </AlertDialogContent>
    </AlertDialog>
  )
}

/** A new password for a user: every session of theirs ends at once, this browser's too when it is your own. */
function NewPasswordDialog({
  asking,
  isSelf,
  onClose,
  onSave,
}: {
  asking: Asking | null
  isSelf: boolean
  onClose: () => void
  onSave: (asking: Asking, password: string) => Promise<unknown>
}) {
  const { t } = useTranslation('auth')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [tried, setTried] = useState(false)
  const [pending, setPending] = useState(false)
  const problem = tried ? passwordProblem(password) : null
  const mismatch = tried && !problem && confirm !== password

  const close = () => {
    setPassword('')
    setConfirm('')
    setTried(false)
    onClose()
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setTried(true)
    if (!asking || passwordProblem(password) || confirm !== password) return
    setPending(true)
    try {
      await onSave(asking, password)
      close()
    } catch {
      // The toast says why; the dialog stays open with what was typed.
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog open={asking !== null} onOpenChange={(open) => !open && close()}>
      <DialogContent className="sm:max-w-md">
        {asking && (
          <form noValidate onSubmit={(event) => void submit(event)} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>{t('users.passwordDialog.title', { name: asking.user.username })}</DialogTitle>
              <DialogDescription>{t(isSelf ? 'users.passwordDialog.ownDescription' : 'users.passwordDialog.description', { name: asking.user.username })}</DialogDescription>
            </DialogHeader>
            <Field label={t('field.newPassword')} hint={t('hint.password')} error={problem ? t(`problem.${problem}`) : null}>
              <PasswordInput value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" showLabel={t('showPassword')} hideLabel={t('hidePassword')} />
            </Field>
            <Field label={t('field.confirm')} error={mismatch ? t('problem.mismatch') : null}>
              <PasswordInput value={confirm} onChange={(event) => setConfirm(event.target.value)} autoComplete="new-password" showLabel={t('showPassword')} hideLabel={t('hidePassword')} />
            </Field>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={close}>
                {t('users.cancel')}
              </Button>
              <Button type="submit" disabled={pending}>
                {t('users.change.password')}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** What each role can do and what deactivating means, next to the list it applies to. */
function RolesPanel() {
  const { t } = useTranslation('auth')
  return (
    <Panel className="xl:col-span-4" title={t('users.roles.title')} description={t('users.roles.question')}>
      <dl className="space-y-4 text-sm">
        <div className="space-y-1.5">
          <dt>
            <RoleBadge kind="administrator" />
          </dt>
          <dd className="text-pretty text-muted-foreground">{t('users.roles.administrator')}</dd>
        </div>
        <div className="space-y-1.5">
          <dt>
            <RoleBadge kind="user" />
          </dt>
          <dd className="text-pretty text-muted-foreground">{t('users.roles.user')}</dd>
        </div>
        <div className="space-y-1.5 border-t pt-4">
          <dt className="text-sm font-medium">{t('users.status.deactivated')}</dt>
          <dd className="text-pretty text-muted-foreground">{t('users.roles.deactivated')}</dd>
        </div>
        <div className="space-y-1.5">
          <dt className="text-sm font-medium">{t('users.roles.passwordTitle')}</dt>
          <dd className="text-pretty text-muted-foreground">{t('users.roles.password')}</dd>
        </div>
      </dl>
    </Panel>
  )
}

/** Whether the account can sign in: a plain word, never a market color. */
function Status({ user }: { user: User }) {
  const { t } = useTranslation('auth')
  const active = user.status === 'active'
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-xs whitespace-nowrap', active ? 'text-foreground' : 'text-muted-foreground')}>
      <span aria-hidden className={cn('size-1.5 rounded-full', active ? 'bg-brand' : 'bg-faint')} />
      {t(`users.status.${user.status}`)}
    </span>
  )
}
