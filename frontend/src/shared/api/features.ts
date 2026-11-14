import { useQuery } from '@tanstack/react-query'
import { apiRequest } from './http'
import type { components } from './schema.gen'
import { useSession, type Permission } from './session'

type Schemas = components['schemas']

/** A part of the product the administrator shows or hides (`features.*` in the settings). */
export type Feature = Schemas['Feature']
export type FeatureVisibility = Schemas['FeatureVisibility']
/** Whom the site shows each feature to, as GET /v1/auth/status answers. */
export type Visibilities = Readonly<Partial<Record<Feature, FeatureVisibility>>>

export const authStatusKey = ['public', 'auth', 'status'] as const

/**
 * Whether the site still needs its first administrator, whether it takes registrations, and whom it shows each
 * feature to. An administrator can change the last two while a tab stays open, so the tab asks again when it is back
 * in focus a minute later.
 */
export function useAuthStatus() {
  return useQuery({
    queryKey: authStatusKey,
    queryFn: ({ signal }) => apiRequest('get', '/v1/auth/status', { signal }),
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  })
}

/**
 * Whether a viewer with these permissions sees the feature: false until the server has said, so a hidden page never
 * shows even for a moment. Hiding is never the protection; the server refuses a hidden feature's every request.
 */
export function shows(visibilities: Visibilities | undefined, permissions: readonly Permission[], feature: Feature): boolean {
  const visibility = visibilities?.[feature]
  return visibility === 'everyone' || (visibility === 'administrators' && permissions.includes('see_administrator_features'))
}

const NO_PERMISSIONS: readonly Permission[] = []

/** What the viewer sees: `shows` answers for one feature or for any one of several, false while `pending`. */
export function useShown() {
  const status = useAuthStatus()
  const current = useSession()
  const permissions = current.status === 'signedIn' ? current.user.permissions : NO_PERMISSIONS
  const visibilities = status.data?.features
  return {
    // A session still being checked has no permissions yet, which would hide an administrator's pages for a moment.
    pending: status.isPending || current.status === 'checking',
    error: status.data ? null : status.error,
    retry: () => void status.refetch(),
    shows: (feature: Feature | readonly Feature[]): boolean =>
      (typeof feature === 'string' ? [feature] : feature).some((item) => shows(visibilities, permissions, item)),
  }
}

export function useShows(feature: Feature | readonly Feature[]): boolean {
  return useShown().shows(feature)
}
