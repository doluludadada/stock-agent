import { Navigate, Outlet, useLocation, useNavigate, useSearchParams } from 'react-router'
import { RegisterScreen, safeNext, SetupScreen, SignInScreen, useAuthStatus, useSessionProbe } from '@/features/auth'
import { useSession } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { AuthLinksProvider } from '@/shared/ui/require-sign-in'

/**
 * Asks the server whether the site has its administrator yet and who is signed in. A site with no account goes to
 * the first-time setup; everything else renders at once, and private parts wait for the answer.
 */
export function AuthGate() {
  const status = useAuthStatus()
  useSessionProbe()
  const session = useSession()
  const location = useLocation()
  const needsSetup = status.data?.needs_first_administrator === true
  if (needsSetup && location.pathname !== paths.setup) return <Navigate to={paths.setup} replace />
  if (status.data && !needsSetup && location.pathname === paths.setup) return <Navigate to={session.status === 'signedIn' ? paths.overview : paths.signIn} replace />
  return (
    <AuthLinksProvider value={{ signIn: paths.signInThen, register: status.data?.registration_open === false ? null : paths.register }}>
      <Outlet />
    </AuthLinksProvider>
  )
}

export function SetupRoute() {
  const navigate = useNavigate()
  return <SetupScreen onDone={() => navigate(paths.overview, { replace: true })} />
}

export function SignInRoute() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const session = useSession()
  const next = safeNext(params.get('next'), paths.overview)
  if (session.status === 'signedIn') return <Navigate to={next} replace />
  return <SignInScreen registerHref={paths.register} onDone={() => navigate(next, { replace: true })} />
}

export function RegisterRoute() {
  const navigate = useNavigate()
  const session = useSession()
  if (session.status === 'signedIn') return <Navigate to={paths.overview} replace />
  return <RegisterScreen signInHref={paths.signIn} onDone={() => navigate(paths.overview, { replace: true })} />
}
