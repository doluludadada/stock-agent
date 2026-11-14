import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { apiRequest, authStatusKey, isApiError, isSameSession, sentInSession, session, SITE_STATE_STALE_MS, useHasPermission, useIsSignedIn, type Schemas, type User } from '@/shared/api'

export { useAuthStatus } from '@/shared/api'

export type AuthStatus = Schemas['AuthStatusResponse']
export type AiModels = Schemas['AiModelResponse']
export type AiProvider = Schemas['AiProvider']

export const authKeys = {
  status: authStatusKey,
  me: ['public', 'auth', 'me'] as const,
  users: ['admin', 'users'] as const,
  aiModel: ['owner', 'settings', 'ai-model'] as const,
}

/**
 * Asks the server whose session this browser's cookie holds: at start, and again whenever the tab comes back into
 * view, so a role changed or a session ended elsewhere shows here. Only a 401 says signed out at once. A server that
 * cannot answer at start is asked again, and counts as signed out only once those tries failed; it is then asked
 * every few seconds, so a signed-in user's pages come back without a reload.
 */
export function useSessionProbe() {
  const probe = useQuery({
    queryKey: authKeys.me,
    queryFn: async ({ signal }): Promise<User | null> => {
      try {
        const user = await apiRequest('get', '/v1/auth/me', { signal })
        session.signIn(user)
        return user
      } catch (error) {
        if (isApiError(error, 'unauthorized')) {
          if (session.current().status === 'checking') session.signOut()
          return null
        }
        throw error
      }
    },
    staleTime: SITE_STATE_STALE_MS,
    refetchOnWindowFocus: true,
    retry: PROBE_RETRIES,
    refetchInterval: (query) => (query.state.status === 'error' ? PROBE_AGAIN_MS : false),
  })
  useEffect(() => {
    if (probe.isError && session.current().status === 'checking') session.signOut()
  }, [probe.isError])
  return probe
}

/** Tries of the first ask after one that the server did not answer, and how often it is asked again after they failed. */
const PROBE_RETRIES = 2
const PROBE_AGAIN_MS = 10_000

function signedIn(client: QueryClient, user: User) {
  session.signIn(user)
  client.setQueryData(authKeys.me, user)
}

function signIn(identifier: string, password: string) {
  return apiRequest('post', '/v1/auth/sign-in', { body: { identifier, password } })
}

export function useSignIn() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ identifier, password }: { identifier: string; password: string }) => signIn(identifier, password),
    onSuccess: (user) => signedIn(client, user),
  })
}

/** The first administrator, with the code the server printed on its console; signed in at once. */
export function useSetUp() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['SetupRequest']) => {
      await apiRequest('post', '/v1/auth/setup', { body })
      return signIn(body.username, body.password)
    },
    onSuccess: (user) => {
      signedIn(client, user)
      client.setQueryData<AuthStatus>(authKeys.status, (status) => status && { ...status, needs_first_administrator: false })
      void client.invalidateQueries({ queryKey: authKeys.status })
    },
  })
}

/** A new user of the role user, signed in at once. */
/**
 * Registers, then signs in. A sign-in that fails after the registration went through leaves the account made, so the
 * next try of the same form signs in only: registering again would answer that the name is taken.
 */
export function useRegister() {
  const client = useQueryClient()
  const registered = useRef<string | null>(null)
  return useMutation({
    mutationFn: async (body: Schemas['RegistrationRequest']) => {
      const account = JSON.stringify(body)
      if (registered.current !== account) await apiRequest('post', '/v1/auth/register', { body })
      registered.current = account
      return signIn(body.username, body.password)
    },
    onSuccess: (user) => signedIn(client, user),
  })
}

export function useSignOut() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => apiRequest('post', '/v1/auth/sign-out'),
    onSuccess: () => {
      session.signOut()
      client.setQueryData(authKeys.me, null)
    },
  })
}

export function useUsers() {
  const allowed = useHasPermission('manage_users')
  return useQuery({ queryKey: authKeys.users, queryFn: ({ signal }) => apiRequest('get', '/v1/admin/users', { signal }), enabled: allowed })
}

export function useChangeUser() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, body }: { userId: string; body: Schemas['UserChangeRequest'] }) =>
      apiRequest('patch', '/v1/admin/users/{user_id}', { params: { user_id: userId }, body }),
    onMutate: sentInSession,
    onSuccess: (changed, _, sent) => {
      if (isSameSession(sent)) client.setQueryData<User[]>(authKeys.users, (users) => users?.map((user) => (user.user_id === changed.user_id ? changed : user)))
    },
  })
}

/** My settings: the AI models the site offers, its default, and the one the signed-in user's runs use. */
export function useAiModels() {
  const signedIn = useIsSignedIn()
  return useQuery({ queryKey: authKeys.aiModel, queryFn: ({ signal }) => apiRequest('get', '/v1/auth/me/ai-model', { signal }), enabled: signedIn })
}

/**
 * Saves the model of the user's next runs, null for the site's default. A model the site stopped offering since the
 * page loaded is refused, and the offer is read again.
 */
export function useChooseAiModel() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (aiModel: AiProvider | null) => apiRequest('put', '/v1/auth/me/ai-model', { body: { confirm: true, ai_model: aiModel } }),
    onMutate: sentInSession,
    onSuccess: (saved, _, sent) => {
      if (isSameSession(sent)) client.setQueryData(authKeys.aiModel, saved)
    },
    onError: (error) => {
      if (isApiError(error) && error.code === 'ai_model_not_offered') void client.invalidateQueries({ queryKey: authKeys.aiModel })
    },
  })
}
