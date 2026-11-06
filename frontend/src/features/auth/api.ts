import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { apiRequest, isApiError, session, useHasPermission, useIsSignedIn, type Schemas, type User } from '@/shared/api'

export type AuthStatus = Schemas['AuthStatusResponse']
export type AiModels = Schemas['AiModelResponse']
export type AiProvider = Schemas['AiProvider']

export const authKeys = {
  status: ['public', 'auth', 'status'] as const,
  me: ['public', 'auth', 'me'] as const,
  users: ['admin', 'users'] as const,
  aiModel: ['owner', 'settings', 'ai-model'] as const,
}

/** Whether the site still needs its first administrator, and whether it takes registrations. */
export function useAuthStatus() {
  return useQuery({
    queryKey: authKeys.status,
    queryFn: ({ signal }) => apiRequest('get', '/v1/auth/status', { signal }),
    staleTime: 5 * 60_000,
  })
}

/**
 * Asks the server whose session this browser's cookie holds: at start, and again whenever the tab comes back into
 * view, so a role changed or a session ended elsewhere shows here. A server that cannot answer at start counts as
 * signed out until the next ask.
 */
export function useSessionProbe() {
  return useQuery({
    queryKey: authKeys.me,
    queryFn: async ({ signal }): Promise<User | null> => {
      try {
        const user = await apiRequest('get', '/v1/auth/me', { signal })
        session.signIn(user)
        return user
      } catch (error) {
        if (session.current().status === 'checking') session.signOut()
        if (isApiError(error, 'unauthorized')) return null
        throw error
      }
    },
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  })
}

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
export function useRegister() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['RegistrationRequest']) => {
      await apiRequest('post', '/v1/auth/register', { body })
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
    onSuccess: (changed) => client.setQueryData<User[]>(authKeys.users, (users) => users?.map((user) => (user.user_id === changed.user_id ? changed : user))),
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
    onSuccess: (saved) => client.setQueryData(authKeys.aiModel, saved),
    onError: (error) => {
      if (isApiError(error) && error.code === 'ai_model_not_offered') void client.invalidateQueries({ queryKey: authKeys.aiModel })
    },
  })
}
